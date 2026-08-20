import pytest

from video.providers.mock_provider import MockVideoProvider
from video.schemas import GenerationMode, JobStatus, VideoRequest
from video.service import VideoGenerationService
from video.repository import InMemoryVideoJobRepository


class RecordingMockVideoProvider(MockVideoProvider):
    """记录 submit 调用次数，用于验证 Router 失败时不会创建任务。"""

    def __init__(self) -> None:
        super().__init__()
        self.submit_call_count = 0

    def submit(self, request, model):
        self.submit_call_count += 1
        return super().submit(request, model)


def make_text_to_video_request(
    *,
    budget_usd: float = 1.0,
    min_quality_score: int = 1,
) -> VideoRequest:
    return VideoRequest(
        prompt="生成一个展示智能手表的短视频。",
        mode=GenerationMode.TEXT_TO_VIDEO,
        duration_seconds=5,
        budget_usd=budget_usd,
        min_quality_score=min_quality_score,
    )


def test_create_job_selects_model_and_submits_queued_job():
    provider = MockVideoProvider()
    service = VideoGenerationService(
    provider,
    InMemoryVideoJobRepository(),
)
    request = make_text_to_video_request(min_quality_score=6)

    submission = service.create_job(request)

    assert submission.selection.model.model_id == "mock-balanced"
    assert submission.selection.estimated_cost_usd == 0.25
    assert submission.job.model_id == "mock-balanced"
    assert submission.job.status == JobStatus.QUEUED


def test_create_job_supports_image_to_video_request():
    service = VideoGenerationService(
        MockVideoProvider(),
        InMemoryVideoJobRepository(),
    )
    request = VideoRequest(
        prompt="让参考图中的手表缓慢旋转。",
        mode=GenerationMode.IMAGE_TO_VIDEO,
        duration_seconds=5,
        budget_usd=1.0,
        reference_image_url="https://example.com/watch.png",
        min_quality_score=6,
    )

    submission = service.create_job(request)

    assert submission.selection.model.model_id == "mock-balanced"
    assert submission.job.model_id == "mock-balanced"
    assert submission.job.status == JobStatus.QUEUED


def test_select_for_request_does_not_submit_provider_job():
    provider = RecordingMockVideoProvider()
    service = VideoGenerationService(
    provider,
    InMemoryVideoJobRepository(),
)

    selection = service.select_for_request(
        make_text_to_video_request(min_quality_score=6)
    )

    assert selection.model.model_id == "mock-balanced"
    assert provider.submit_call_count == 0


def test_submit_selected_uses_the_previously_selected_model():
    provider = RecordingMockVideoProvider()
    service = VideoGenerationService(
    provider,
    InMemoryVideoJobRepository(),
)
    request = make_text_to_video_request(min_quality_score=6)
    selection = service.select_for_request(request)

    job = service.submit_selected(request, selection)

    assert job.model_id == selection.model.model_id
    assert job.status == JobStatus.QUEUED
    assert provider.submit_call_count == 1


def test_create_job_does_not_submit_when_router_rejects_request():
    provider = RecordingMockVideoProvider()
    service = VideoGenerationService(
        MockVideoProvider(),
        InMemoryVideoJobRepository(),
    )
    request = make_text_to_video_request(budget_usd=0.09)

    with pytest.raises(ValueError, match="预算"):
        service.create_job(request)

    assert provider.submit_call_count == 0


def test_get_job_delegates_to_provider_poll():
    service = VideoGenerationService(
        MockVideoProvider(),
        InMemoryVideoJobRepository(),
    )
    submission = service.create_job(make_text_to_video_request())

    processing_job = service.get_job(submission.job.job_id)
    assert processing_job.status == JobStatus.PROCESSING

    completed_job = service.get_job(submission.job.job_id)
    assert completed_job.status == JobStatus.COMPLETED
    assert completed_job.output_url == (
        f"https://example.com/videos/{submission.job.job_id}.mp4"
    )

def test_create_job_saves_job_to_repository():
    provider = MockVideoProvider()
    repository = InMemoryVideoJobRepository()
    service = VideoGenerationService(provider, repository)

    submission = service.create_job(
        make_text_to_video_request(min_quality_score=6)
    )

    saved_job = repository.get(submission.job.job_id)

    assert saved_job is not None
    assert saved_job.job_id == submission.job.job_id
    assert saved_job.status == JobStatus.QUEUED

def test_polling_persists_latest_job_status():
    repository = InMemoryVideoJobRepository()
    service = VideoGenerationService(
        MockVideoProvider(),
        repository,
    )

    submission = service.create_job(
        make_text_to_video_request()
    )

    processing_job = service.get_job(submission.job.job_id)
    saved_processing_job = repository.get(
        submission.job.job_id
    )

    assert saved_processing_job is not None
    assert saved_processing_job.status == processing_job.status
    assert saved_processing_job.status == JobStatus.PROCESSING

    completed_job = service.get_job(submission.job.job_id)
    saved_completed_job = repository.get(
        submission.job.job_id
    )

    assert saved_completed_job is not None
    assert saved_completed_job.status == completed_job.status
    assert saved_completed_job.status == JobStatus.COMPLETED
