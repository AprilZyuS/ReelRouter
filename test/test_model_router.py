import pytest

from video.costing import estimate_generation_cost
from video.model_router import select_model
from video.schemas import GenerationMode, VideoRequest


def make_request(
    mode: GenerationMode = GenerationMode.TEXT_TO_VIDEO,
    duration_seconds: int = 5,
    budget_usd: float = 1.0,
    reference_image_url: str | None = None,
    min_quality_score: int = 1,
) -> VideoRequest:
    return VideoRequest(
        prompt="生成一个展示智能手表的短视频。",
        mode=mode,
        duration_seconds=duration_seconds,
        budget_usd=budget_usd,
        reference_image_url=reference_image_url,
        min_quality_score=min_quality_score,
    )


def test_router_selects_balanced_for_quality_six_within_budget():
    request = make_request(budget_usd=1.0, min_quality_score=6)

    selection = select_model(request)

    assert selection.model.model_id == "mock-balanced"
    assert selection.estimated_cost_usd == 0.25


def test_router_selects_premium_for_quality_eight():
    request = make_request(budget_usd=1.0, min_quality_score=8)

    selection = select_model(request)

    assert selection.model.model_id == "mock-premium"
    assert selection.estimated_cost_usd == 0.6


def test_router_selects_economy_when_low_quality_is_acceptable():
    request = make_request(budget_usd=0.15, min_quality_score=5)

    selection = select_model(request)

    assert selection.model.model_id == "mock-economy"
    assert selection.estimated_cost_usd == 0.1


def test_router_selects_balanced_for_image_to_video():
    request = make_request(
        mode=GenerationMode.IMAGE_TO_VIDEO,
        budget_usd=1.0,
        min_quality_score=6,
        reference_image_url="https://example.com/watch.png",
    )

    selection = select_model(request)

    assert selection.model.model_id == "mock-balanced"


def test_router_selects_premium_for_twelve_second_video():
    request = make_request(
        duration_seconds=12,
        budget_usd=2.0,
        min_quality_score=8,
    )

    selection = select_model(request)

    assert selection.model.model_id == "mock-premium"
    assert selection.estimated_cost_usd == 1.44


def test_router_rejects_duration_that_no_model_supports():
    request = make_request(duration_seconds=16, budget_usd=10.0)

    with pytest.raises(ValueError, match="生成模式或视频时长"):
        select_model(request)


def test_router_rejects_request_when_budget_is_too_low():
    request = make_request(budget_usd=0.09, min_quality_score=1)

    with pytest.raises(ValueError, match="预算"):
        select_model(request)


def test_router_rejects_request_when_affordable_models_are_too_low_quality():
    request = make_request(budget_usd=0.3, min_quality_score=8)

    with pytest.raises(ValueError, match="最低质量"):
        select_model(request)


def test_router_selection_cost_matches_costing_function():
    request = make_request(budget_usd=1.0, min_quality_score=6)

    selection = select_model(request)
    expected_cost = estimate_generation_cost(request, selection.model)

    assert selection.estimated_cost_usd == expected_cost
    assert "成本最低" in selection.reason
