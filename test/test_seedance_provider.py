"""Seedance Provider 的无网络契约测试。"""

import json

import httpx
import pytest

from video.ark_video_config import ArkVideoSettings
from video.model_registry import build_seedance_model
from video.providers.seedance_provider import SeedanceProvider
from video.schemas import (
    CostRecord,
    CostSource,
    GenerationMode,
    JobStatus,
    VideoGenerationJob,
    VideoRequest,
)


def make_model():
    return build_seedance_model(cost_per_second=0.2)


def make_request(mode: GenerationMode = GenerationMode.TEXT_TO_VIDEO) -> VideoRequest:
    return VideoRequest(
        prompt="雨夜港口，一名女子握着一封匿名来信，电影感中景。",
        mode=mode,
        duration_seconds=4,
        budget_usd=2.0,
        reference_image_url=(
            "https://assets.example/lin-xiao.png"
            if mode == GenerationMode.IMAGE_TO_VIDEO
            else None
        ),
    )


def make_provider(transport: httpx.MockTransport) -> SeedanceProvider:
    client = httpx.Client(
        transport=transport,
        base_url="https://ark.example/api/v3/",
    )
    return SeedanceProvider(
        ArkVideoSettings(
            api_key="test-key",
            model="ep-seedance-test",
            estimated_cost_per_second_usd=0.2,
            base_url="https://ark.example/api/v3",
        ),
        client=client,
    )


def test_submit_text_to_video_uses_ark_async_contract():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v3/contents/generations/tasks"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "model": "ep-seedance-test",
            "content": [{"type": "text", "text": make_request().prompt}],
            "ratio": "16:9",
            "duration": 4,
            "watermark": False,
        }
        return httpx.Response(200, json={"id": "cgt-seedance-1"})

    job = make_provider(httpx.MockTransport(handler)).submit(make_request(), make_model())

    assert job.job_id == "cgt-seedance-1"
    assert job.provider == "seedance"
    assert job.status is JobStatus.QUEUED
    assert job.cost.estimated_usd == 0.8


def test_submit_image_to_video_sends_reference_image_in_content_array():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["content"][1] == {
            "type": "image_url",
            "image_url": {"url": "https://assets.example/lin-xiao.png"},
            "role": "reference_image",
        }
        return httpx.Response(200, json={"id": "cgt-seedance-image"})

    job = make_provider(httpx.MockTransport(handler)).submit(
        make_request(GenerationMode.IMAGE_TO_VIDEO), make_model()
    )

    assert job.status is JobStatus.QUEUED


def test_poll_maps_ark_statuses_and_reads_completed_video_url():
    responses = iter(
        [
            {"status": "queued"},
            {"status": "running"},
            {
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example/seedance.mp4"},
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v3/contents/generations/tasks/cgt-restored"
        return httpx.Response(200, json=next(responses))

    provider = make_provider(httpx.MockTransport(handler))
    previous = VideoGenerationJob(
        job_id="cgt-restored",
        model_id="seedance-2.x",
        status=JobStatus.QUEUED,
        cost=CostRecord(estimated_usd=0.8, reported_usd=None, source=CostSource.ESTIMATED),
        provider="seedance",
        request=make_request(),
    )

    assert provider.poll(previous).status is JobStatus.QUEUED
    assert provider.poll(previous).status is JobStatus.PROCESSING
    completed = provider.poll(previous)
    assert completed.status is JobStatus.COMPLETED
    assert completed.output_url == "https://cdn.example/seedance.mp4"


def test_poll_records_provider_failure_and_retry_guidance():
    provider = make_provider(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "status": "failed",
                    "error": {"code": "QuotaExceeded", "message": "too many tasks"},
                },
            )
        )
    )
    previous = VideoGenerationJob(
        job_id="cgt-failed",
        model_id="seedance-2.x",
        status=JobStatus.PROCESSING,
        cost=CostRecord(estimated_usd=0.8, reported_usd=None, source=CostSource.ESTIMATED),
        provider="seedance",
        request=make_request(),
    )

    failed = provider.poll(previous)

    assert failed.status is JobStatus.FAILED
    assert failed.failure_code == "QuotaExceeded"
    assert failed.retryable is True


def test_provider_rejects_a_job_belonging_to_another_provider():
    provider = make_provider(
        httpx.MockTransport(lambda request: pytest.fail("不应发起 HTTP 请求"))
    )
    previous = VideoGenerationJob(
        job_id="runway-job",
        model_id="runway-gen4.5",
        status=JobStatus.QUEUED,
        cost=CostRecord(estimated_usd=0.5, reported_usd=None, source=CostSource.ESTIMATED),
        provider="runway",
    )

    with pytest.raises(ValueError, match="provider 为 seedance"):
        provider.poll(previous)
