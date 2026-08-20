import pytest

from video.budget_guard import evaluate_budget
from video.model_router import ModelSelection, select_model
from video.model_registry import get_model
from video.schemas import GenerationMode, VideoRequest


def make_request(
    *,
    duration_seconds: int = 5,
    budget_usd: float = 1.0,
    min_quality_score: int = 6,
) -> VideoRequest:
    return VideoRequest(
        prompt="一只橙色小猫在窗边打盹。",
        mode=GenerationMode.TEXT_TO_VIDEO,
        duration_seconds=duration_seconds,
        budget_usd=budget_usd,
        min_quality_score=min_quality_score,
    )


def test_low_cost_selection_is_auto_approved():
    request = make_request()
    selection = select_model(request)

    decision = evaluate_budget(request, selection, auto_approval_limit=0.50)

    assert selection.estimated_cost_usd == 0.25
    assert decision.action == "auto_approve"
    assert "自动审批额度" in decision.reason


def test_high_cost_selection_requires_human_review():
    request = make_request(
        duration_seconds=12,
        budget_usd=2.0,
        min_quality_score=8,
    )
    selection = select_model(request)

    decision = evaluate_budget(request, selection, auto_approval_limit=0.50)

    assert selection.model.model_id == "mock-premium"
    assert selection.estimated_cost_usd == 1.44
    assert decision.action == "needs_human_review"
    assert "人工确认" in decision.reason


def test_selection_over_user_budget_is_rejected_defensively():
    request = make_request(budget_usd=1.0)
    selection = ModelSelection(
        model=get_model("mock-premium"),
        estimated_cost_usd=1.44,
        reason="测试用的越预算选择。",
    )

    decision = evaluate_budget(request, selection)

    assert decision.action == "reject"
    assert "超过用户预算" in decision.reason


def test_negative_auto_approval_limit_is_invalid():
    request = make_request()
    selection = select_model(request)

    with pytest.raises(ValueError, match="不能小于 0"):
        evaluate_budget(request, selection, auto_approval_limit=-0.01)
