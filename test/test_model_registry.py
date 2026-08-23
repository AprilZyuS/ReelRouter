import pytest

from video.model_registry import build_seedance_model, get_model, list_models, supports_request
from video.schemas import GenerationMode, VideoRequest

@pytest.mark.parametrize("min_quality_score", [0, 11])
def test_video_request_rejects_invalid_min_quality_score(min_quality_score):
    with pytest.raises(ValueError, match="min_quality_score"):
        VideoRequest(
            prompt="生成智能手表广告视频。",
            mode=GenerationMode.TEXT_TO_VIDEO,
            duration_seconds=5,
            budget_usd=1.0,
            min_quality_score=min_quality_score,
        )

def make_request(
    mode: GenerationMode = GenerationMode.TEXT_TO_VIDEO,
    duration_seconds: int = 5,
    reference_image_url: str | None = None,
) -> VideoRequest:
    return VideoRequest(
        prompt="生成一个展示智能手表的短视频。",
        mode=mode,
        duration_seconds=duration_seconds,
        budget_usd=1.0,
        reference_image_url=reference_image_url,
    )


def test_list_models_returns_all_mock_models():
    model_ids = {model.model_id for model in list_models()}

    assert model_ids == {"mock-economy", "mock-balanced", "mock-premium"}


def test_get_model_returns_requested_profile():
    model = get_model("mock-balanced")

    assert model.provider == "mock-provider"
    assert model.quality_score == 7


def test_get_model_raises_for_unknown_model_id():
    with pytest.raises(ValueError, match="不存在模型"):
        get_model("model-does-not-exist")


def test_seedance_profile_has_its_documented_duration_boundary():
    model = build_seedance_model(cost_per_second=0.15)

    assert model.provider == "seedance"
    assert model.min_duration_seconds == 4
    assert model.max_duration_seconds == 15


def test_economy_does_not_support_image_to_video():
    model = get_model("mock-economy")
    request = make_request(
        mode=GenerationMode.IMAGE_TO_VIDEO,
        reference_image_url="https://example.com/watch.png",
    )

    assert supports_request(model, request) is False


def test_balanced_supports_image_to_video():
    model = get_model("mock-balanced")
    request = make_request(
        mode=GenerationMode.IMAGE_TO_VIDEO,
        reference_image_url="https://example.com/watch.png",
    )

    assert supports_request(model, request) is True


def test_model_does_not_support_duration_over_its_limit():
    model = get_model("mock-economy")
    request = make_request(duration_seconds=6)

    assert supports_request(model, request) is False


def test_image_to_video_requires_reference_image():
    with pytest.raises(ValueError, match="reference_image_url"):
        make_request(mode=GenerationMode.IMAGE_TO_VIDEO)


def test_video_request_rejects_invalid_duration():
    with pytest.raises(ValueError, match="duration_seconds"):
        make_request(duration_seconds=0)
