"""以显式环境配置选择开发 Mock 或真实 Runway Provider。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from video.ark_video_config import ArkVideoSettings
from video.model_registry import build_seedance_model, list_models
from video.providers.base import VideoProvider
from video.providers.mock_provider import MockVideoProvider
from video.providers.runway_provider import RunwayProvider
from video.providers.seedance_provider import SeedanceProvider
from video.runway_config import RunwaySettings
from video.schemas import VideoModelProfile


@dataclass(frozen=True)
class ProviderBundle:
    provider_name: str
    provider: VideoProvider
    models: tuple[VideoModelProfile, ...]


def create_provider_bundle(provider_name: str | None = None) -> ProviderBundle:
    selected = (provider_name or os.getenv("VIDEO_PROVIDER", "mock")).strip().lower()
    if selected == "mock":
        return ProviderBundle("mock", MockVideoProvider(), tuple(list_models(provider="mock")))
    if selected == "runway":
        return ProviderBundle(
            "runway",
            RunwayProvider(RunwaySettings.from_environment()),
            tuple(list_models(provider="runway")),
        )
    if selected == "seedance":
        settings = ArkVideoSettings.from_environment()
        return ProviderBundle(
            "seedance",
            SeedanceProvider(settings),
            (build_seedance_model(cost_per_second=settings.estimated_cost_per_second_usd),),
        )
    raise ValueError("VIDEO_PROVIDER 只能是 mock、runway 或 seedance。")
