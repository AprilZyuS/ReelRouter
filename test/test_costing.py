import pytest

from video.costing import estimate_generation_cost
from video.model_registry import get_model
from video.schemas import GenerationMode, VideoRequest


def make_request(
    mode: GenerationMode = GenerationMode.TEXT_TO_VIDEO,
    duration_seconds: int = 5,
    budget_usd: float = 2.0,
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


def test_costing_calculates_balanced_model_cost():
    request = make_request(duration_seconds=5)
    model = get_model("mock-balanced")

    assert estimate_generation_cost(request, model) == 0.25


def test_costing_calculates_premium_long_video_cost():
    request = make_request(duration_seconds=12)
    model = get_model("mock-premium")

    assert estimate_generation_cost(request, model) == 1.44


def test_costing_rejects_request_that_model_cannot_execute():
    request = make_request(
        mode=GenerationMode.IMAGE_TO_VIDEO,
        reference_image_url="https://example.com/watch.png",
    )
    model = get_model("mock-economy")

    with pytest.raises(ValueError, match="不支持"):
        estimate_generation_cost(request, model)
