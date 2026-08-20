from langgraph.types import Command

from video.checkpoint import create_video_checkpointer
from video.providers.mock_provider import MockVideoProvider
from video.schemas import GenerationMode, JobStatus, VideoRequest
from video.service import VideoGenerationService
from video.workflow import build_video_workflow
from video.repository import InMemoryVideoJobRepository


class TrackingMockVideoProvider(MockVideoProvider):
    """记录任务是否在人工批准前被意外提交。"""

    def __init__(self) -> None:
        super().__init__()
        self.submit_call_count = 0

    def submit(self, request, model):
        self.submit_call_count += 1
        return super().submit(request, model)


def make_high_cost_request() -> VideoRequest:
    return VideoRequest(
        prompt="一支电影感的城市夜景短片。",
        mode=GenerationMode.TEXT_TO_VIDEO,
        duration_seconds=12,
        budget_usd=2.0,
        min_quality_score=8,
    )


def pause_at_human_review():
    provider = TrackingMockVideoProvider()
    workflow = build_video_workflow(
        VideoGenerationService(
    provider,
    InMemoryVideoJobRepository(),
),
        auto_approval_limit=0.50,
        checkpointer=create_video_checkpointer(),
    )
    config = {"configurable": {"thread_id": "video-human-review-test"}}

    result = workflow.invoke({"request": make_high_cost_request()}, config=config)
    return workflow, provider, config, result


def test_high_cost_job_pauses_before_provider_submission():
    _, provider, _, result = pause_at_human_review()

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["model_id"] == "mock-premium"
    assert payload["estimated_cost_usd"] == 1.44
    assert payload["options"] == ["approve", "reject"]
    assert provider.submit_call_count == 0


def test_human_approval_submits_queued_job():
    workflow, provider, config, _ = pause_at_human_review()

    result = workflow.invoke(
        Command(resume={"action": "approve", "feedback": "预算已确认。"}),
        config=config,
    )

    assert result["approval_status"] == "approved"
    assert result["approval_feedback"] == "预算已确认。"
    assert result["job"].status == JobStatus.QUEUED
    assert provider.submit_call_count == 1
    assert workflow.get_state(config).next == ()


def test_human_rejection_ends_without_submitting_job():
    workflow, provider, config, _ = pause_at_human_review()

    result = workflow.invoke(
        Command(resume={"action": "reject", "feedback": "成本过高。"}),
        config=config,
    )

    assert result["approval_status"] == "rejected"
    assert result["approval_feedback"] == "成本过高。"
    assert result["error"] == "成本过高。"
    assert "job" not in result
    assert provider.submit_call_count == 0
    assert workflow.get_state(config).next == ()
