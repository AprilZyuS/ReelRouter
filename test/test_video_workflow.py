from video.providers.mock_provider import MockVideoProvider
from video.schemas import GenerationMode, JobStatus, VideoRequest
from video.service import VideoGenerationService
from video.workflow import build_video_workflow
from video.repository import InMemoryVideoJobRepository

class TrackingMockVideoProvider(MockVideoProvider):
    """记录提交与轮询次数，确保 Graph 真实驱动 Provider。"""

    def __init__(self) -> None:
        super().__init__()
        self.submit_call_count = 0
        self.poll_call_count = 0

    def submit(self, request, model):
        self.submit_call_count += 1
        return super().submit(request, model)

    def poll(self, job_id: str):
        self.poll_call_count += 1
        return super().poll(job_id)


def make_text_to_video_request(
    *,
    budget_usd: float = 1.0,
    min_quality_score: int = 6,
) -> VideoRequest:
    return VideoRequest(
        prompt="一只橙色小猫在窗边打盹。",
        mode=GenerationMode.TEXT_TO_VIDEO,
        duration_seconds=5,
        budget_usd=budget_usd,
        min_quality_score=min_quality_score,
    )


def test_workflow_submits_text_to_video_job_without_polling():
    provider = TrackingMockVideoProvider()
    workflow = build_video_workflow(VideoGenerationService(
    provider,
    InMemoryVideoJobRepository(),
))

    result = workflow.invoke({"request": make_text_to_video_request()})

    assert result["selection"].model.model_id == "mock-balanced"
    assert result["job"].status == JobStatus.QUEUED
    assert result["job"].output_url is None
    assert provider.submit_call_count == 1
    assert provider.poll_call_count == 0


def test_workflow_completes_image_to_video_job():
    workflow = build_video_workflow(
        VideoGenerationService(
            MockVideoProvider(),
            InMemoryVideoJobRepository(),
        )
    )   
    request = VideoRequest(
        prompt="让参考图中的手表缓慢旋转。",
        mode=GenerationMode.IMAGE_TO_VIDEO,
        duration_seconds=5,
        budget_usd=1.0,
        min_quality_score=6,
        reference_image_url="https://example.com/watch.png",
    )

    result = workflow.invoke({"request": request})

    assert result["selection"].model.model_id == "mock-balanced"
    assert result["job"].status == JobStatus.QUEUED


def test_workflow_ends_with_error_when_router_rejects_budget():
    provider = TrackingMockVideoProvider()
    workflow = build_video_workflow(VideoGenerationService(
    provider,
    InMemoryVideoJobRepository(),
))
    request = make_text_to_video_request(
        budget_usd=0.09,
        min_quality_score=1,
    )

    result = workflow.invoke({"request": request})

    assert "预算" in result["error"]
    assert "selection" not in result
    assert "job" not in result
    assert provider.submit_call_count == 0
    assert provider.poll_call_count == 0


def test_workflow_leaves_polling_to_the_async_query_endpoint():
    provider = TrackingMockVideoProvider()
    workflow = build_video_workflow(VideoGenerationService(
    provider,
    InMemoryVideoJobRepository(),
))

    result = workflow.invoke({"request": make_text_to_video_request()})

    assert provider.poll_call_count == 0
    assert result["job"].status == JobStatus.QUEUED
