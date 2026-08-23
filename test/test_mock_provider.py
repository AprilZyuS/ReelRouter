import pytest

from video.model_registry import get_model
from video.providers.mock_provider import MockVideoProvider
from video.schemas import (
    CostRecord,
    CostSource,
    GenerationMode,
    JobStatus,
    VideoGenerationJob,
    VideoRequest,
)


def make_text_to_video_request(duration_seconds: int = 5) -> VideoRequest:
    return VideoRequest(
        prompt="生成一个展示智能手表的短视频。",
        mode=GenerationMode.TEXT_TO_VIDEO,
        duration_seconds=duration_seconds,
        budget_usd=1.0,
    )


def test_estimate_cost_uses_model_price_and_duration():
    provider = MockVideoProvider()
    request = make_text_to_video_request(duration_seconds=5)
    model = get_model("mock-economy")

    assert provider.estimate_cost(request, model) == 0.1


def test_estimate_cost_rejects_unsupported_request():
    provider = MockVideoProvider()
    request = VideoRequest(
        prompt="让参考图中的手表动起来。",
        mode=GenerationMode.IMAGE_TO_VIDEO,
        duration_seconds=5,
        budget_usd=1.0,
        reference_image_url="https://example.com/watch.png",
    )
    model = get_model("mock-economy")

    with pytest.raises(ValueError, match="不支持"):
        provider.estimate_cost(request, model)


def test_submit_creates_queued_job_without_output_url():
    provider = MockVideoProvider()
    job = provider.submit(make_text_to_video_request(), get_model("mock-economy"))

    assert job.job_id
    assert job.status == JobStatus.QUEUED
    assert job.cost.estimated_usd == 0.1
    assert job.cost.reported_usd is None
    assert job.cost.source == CostSource.ESTIMATED
    assert job.output_url is None


def test_first_poll_changes_job_to_processing():
    provider = MockVideoProvider()
    job = provider.submit(make_text_to_video_request(), get_model("mock-economy"))

    updated_job = provider.poll(job)

    assert updated_job.status == JobStatus.PROCESSING
    assert updated_job.output_url is None


def test_second_poll_completes_job_and_returns_video_url():
    provider = MockVideoProvider()
    job = provider.submit(make_text_to_video_request(), get_model("mock-economy"))

    provider.poll(job)
    completed_job = provider.poll(job)

    assert completed_job.status == JobStatus.COMPLETED
    assert completed_job.output_url == f"https://example.com/videos/{job.job_id}.mp4"


def test_completed_job_stays_completed_when_polled_again():
    provider = MockVideoProvider()
    job = provider.submit(make_text_to_video_request(), get_model("mock-economy"))

    provider.poll(job)
    completed_job = provider.poll(job)
    polled_again_job = provider.poll(job)

    assert polled_again_job.status == JobStatus.COMPLETED
    assert polled_again_job.output_url == completed_job.output_url


def test_poll_unknown_job_id_raises_value_error():
    provider = MockVideoProvider()

    with pytest.raises(ValueError, match="不存在任务"):
        provider.poll(
            VideoGenerationJob(
                job_id="unknown-job-id",
                model_id="mock-economy",
                status=JobStatus.QUEUED,
                cost=CostRecord(estimated_usd=0, reported_usd=None, source=CostSource.ESTIMATED),
            )
        )
