"""Runway Provider 的无网络单元测试。"""

import json

import httpx
import pytest

from video.providers.runway_provider import RunwayProvider
from video.runway_config import RunwaySettings
from video.schemas import (
    CostRecord,
    CostSource,
    GenerationMode,
    JobStatus,
    VideoGenerationJob,
    VideoModelProfile,
    VideoRequest,
)


def make_runway_model() -> VideoModelProfile:
    return VideoModelProfile(
        model_id="runway-gen4.5",
        provider="runway",
        supported_modes=frozenset(
            {GenerationMode.TEXT_TO_VIDEO, GenerationMode.IMAGE_TO_VIDEO}
        ),
        cost_per_second=0.12,
        estimated_latency_seconds=60,
        quality_score=9,
        min_duration_seconds=2,
        max_duration_seconds=10,
    )


def make_request(mode: GenerationMode = GenerationMode.TEXT_TO_VIDEO) -> VideoRequest:
    return VideoRequest(
        prompt="一只金毛在夕阳下的海边奔跑。",
        mode=mode,
        duration_seconds=5,
        budget_usd=2.0,
        reference_image_url=(
            "https://example.com/dog.png"
            if mode == GenerationMode.IMAGE_TO_VIDEO
            else None
        ),
    )


def make_provider(transport: httpx.MockTransport) -> RunwayProvider:
    client = httpx.Client(
        transport=transport,
        base_url="https://api.dev.runwayml.com/v1/",
    )
    return RunwayProvider(RunwaySettings(api_key="test-key"), client=client)


def test_submit_text_to_video_uses_correct_endpoint_headers_and_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/text_to_video"
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.headers["x-runway-version"] == "2024-11-06"
        assert json.loads(request.content) == {
            "model": "gen4.5",
            "promptText": "一只金毛在夕阳下的海边奔跑。",
            "duration": 5,
            "ratio": "1280:720",
        }
        return httpx.Response(200, json={"id": "runway-job-1"})

    job = make_provider(httpx.MockTransport(handler)).submit(
        make_request(), make_runway_model()
    )

    assert job.job_id == "runway-job-1"
    assert job.status == JobStatus.QUEUED
    assert job.model_id == "runway-gen4.5"
    assert job.cost.estimated_usd == 0.6
    assert job.cost.reported_usd is None
    assert job.cost.source == CostSource.ESTIMATED


def test_submit_image_to_video_sends_reference_image():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/image_to_video"
        assert json.loads(request.content)["promptImage"] == "https://example.com/dog.png"
        return httpx.Response(200, json={"id": "runway-job-2"})

    job = make_provider(httpx.MockTransport(handler)).submit(
        make_request(GenerationMode.IMAGE_TO_VIDEO), make_runway_model()
    )

    assert job.status == JobStatus.QUEUED


def test_poll_maps_pending_running_and_succeeded_to_domain_job_states():
    statuses = iter(
        [
            {"status": "PENDING"},
            {"status": "RUNNING"},
            {"status": "SUCCEEDED", "output": ["https://cdn.runway/video.mp4"]},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "runway-job-3"})
        assert request.url.path == "/v1/tasks/runway-job-3"
        return httpx.Response(200, json=next(statuses))

    provider = make_provider(httpx.MockTransport(handler))
    submitted = provider.submit(make_request(), make_runway_model())

    assert provider.poll(submitted).status == JobStatus.QUEUED
    processing = provider.poll(submitted)
    assert processing.status == JobStatus.PROCESSING
    completed = provider.poll(processing)

    assert completed.status == JobStatus.COMPLETED
    assert completed.output_url == "https://cdn.runway/video.mp4"


def test_poll_maps_failed_task_to_failed_job():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "runway-job-4"})
        return httpx.Response(200, json={"status": "FAILED"})

    provider = make_provider(httpx.MockTransport(handler))
    submitted = provider.submit(make_request(), make_runway_model())

    assert provider.poll(submitted).status == JobStatus.FAILED


def test_submit_converts_http_error_to_clear_runtime_error():
    provider = make_provider(
        httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "bad key"}))
    )

    with pytest.raises(RuntimeError, match="Runway API 请求失败"):
        provider.submit(make_request(), make_runway_model())


def test_poll_job_for_other_provider_is_rejected_before_requesting_runway():
    provider = make_provider(
        httpx.MockTransport(lambda request: pytest.fail("不应该发送 HTTP 请求"))
    )

    submitted = VideoGenerationJob(
        job_id="unknown-job",
        model_id="mock-economy",
        status=JobStatus.QUEUED,
        cost=CostRecord(estimated_usd=0, reported_usd=None, source=CostSource.ESTIMATED),
        provider="mock-provider",
    )
    with pytest.raises(ValueError, match="provider 为 runway"):
        provider.poll(submitted)
@pytest.mark.parametrize(
    ("failure_code", "expected_retryable"),
    [
        ("SAFETY.INPUT.TEXT", False),
        ("INPUT_PREPROCESSING.SAFETY.TEXT", False),
        ("ASSET.INVALID", False),
        ("INTERNAL.BAD_OUTPUT.01", True),
        ("THIRD_PARTY.UNAVAILABLE", True),
    ],
)
def test_poll_maps_runway_failure_code_to_retry_policy(
    failure_code: str,
    expected_retryable: bool,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "runway-failure-job"})
        return httpx.Response(
            200,
            json={
                "status": "FAILED",
                "failureCode": failure_code,
                "failure": "provider failure detail",
            },
        )

    provider = make_provider(httpx.MockTransport(handler))
    submitted = provider.submit(make_request(), make_runway_model())
    failed = provider.poll(submitted)

    assert failed.status == JobStatus.FAILED
    assert failed.failure_code == failure_code
    assert failed.failure_message == "provider failure detail"
    assert failed.retryable is expected_retryable


def test_poll_unknown_failure_code_requires_human_decision():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "runway-unknown-failure"})
        return httpx.Response(
            200,
            json={"status": "FAILED", "failureCode": "NEW.UNKNOWN"},
        )

    provider = make_provider(httpx.MockTransport(handler))
    submitted = provider.submit(make_request(), make_runway_model())

    assert provider.poll(submitted).retryable is None


def test_poll_canceled_task_is_not_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "runway-canceled-job"})
        return httpx.Response(200, json={"status": "CANCELED"})

    provider = make_provider(httpx.MockTransport(handler))
    submitted = provider.submit(make_request(), make_runway_model())
    canceled = provider.poll(submitted)

    assert canceled.status == JobStatus.FAILED
    assert canceled.failure_message == "任务已被取消。"
    assert canceled.retryable is False


def test_poll_uses_persisted_job_snapshot_not_process_local_cache():
    """模拟进程重启后，仍可凭保存的任务快照重新查询 Provider。"""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/tasks/runway-restored-job"
        return httpx.Response(
            200,
            json={
                "status": "SUCCEEDED",
                "output": ["https://cdn.runway.example/restored.mp4"],
            },
        )

    provider = make_provider(httpx.MockTransport(handler))
    restored_job = VideoGenerationJob(
        job_id="runway-restored-job",
        model_id="runway-gen4.5",
        status=JobStatus.PROCESSING,
        cost=CostRecord(
            estimated_usd=0.6,
            reported_usd=None,
            source=CostSource.ESTIMATED,
        ),
        provider="runway",
        request=make_request(),
    )

    job = provider.poll(restored_job)

    assert job.status == JobStatus.COMPLETED
    assert job.output_url == "https://cdn.runway.example/restored.mp4"
    assert job.request == restored_job.request
