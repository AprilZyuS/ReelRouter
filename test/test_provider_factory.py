"""Provider 工厂的配置边界测试。"""

import pytest

from video.provider_factory import VideoProviderConfigurationError, create_provider_bundle


def test_seedance_bundle_uses_video_specific_environment_configuration(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    monkeypatch.setenv("ARK_BASE_URL", "https://ark.example/api/v3")
    monkeypatch.setenv("DOUBAO_VIDEO_MODEL", "ep-seedance-test")
    monkeypatch.setenv("SEEDANCE_ESTIMATED_COST_PER_SECOND_USD", "0.15")

    bundle = create_provider_bundle("seedance")

    assert bundle.provider_name == "seedance"
    assert bundle.models[0].model_id == "seedance-2.x"
    assert bundle.models[0].cost_per_second == 0.15


def test_seedance_bundle_requires_explicit_budget_estimate(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    monkeypatch.setenv("DOUBAO_VIDEO_MODEL", "ep-seedance-test")
    monkeypatch.delenv("SEEDANCE_ESTIMATED_COST_PER_SECOND_USD", raising=False)

    with pytest.raises(VideoProviderConfigurationError, match="SEEDANCE_ESTIMATED_COST_PER_SECOND_USD"):
        create_provider_bundle("seedance")


def test_runway_bundle_returns_a_typed_configuration_error_when_key_is_missing(monkeypatch):
    monkeypatch.delenv("RUNWAY_API_KEY", raising=False)

    with pytest.raises(VideoProviderConfigurationError, match="RUNWAY_API_KEY"):
        create_provider_bundle("runway")
