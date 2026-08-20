from video.schemas import GenerationMode, VideoModelProfile, VideoRequest

# 以下数值均为本项目的 Mock 数据，不代表任何真实供应商的价格或性能。
MODELS = {
    "mock-economy": VideoModelProfile(
        model_id="mock-economy",
        provider="mock-provider",
        supported_modes=frozenset({GenerationMode.TEXT_TO_VIDEO}),
        cost_per_second=0.02,
        estimated_latency_seconds=15,
        quality_score=5,
        min_duration_seconds=1,
        max_duration_seconds=5,
    ),
    "mock-balanced": VideoModelProfile(
        model_id="mock-balanced",
        provider="mock-provider",
        supported_modes=frozenset(
            {GenerationMode.TEXT_TO_VIDEO, GenerationMode.IMAGE_TO_VIDEO}
        ),
        cost_per_second=0.05,
        estimated_latency_seconds=30,
        quality_score=7,
        min_duration_seconds=1,
        max_duration_seconds=10,
    ),
    "mock-premium": VideoModelProfile(
        model_id="mock-premium",
        provider="mock-provider",
        supported_modes=frozenset(
            {GenerationMode.TEXT_TO_VIDEO, GenerationMode.IMAGE_TO_VIDEO}
        ),
        cost_per_second=0.12,
        estimated_latency_seconds=60,
        quality_score=9,
        min_duration_seconds=1,
        max_duration_seconds=15,
    ),
}


def list_models() -> list[VideoModelProfile]:
    return list(MODELS.values())


def get_model(model_id: str) -> VideoModelProfile:
    try:
        return MODELS[model_id]
    except KeyError as error:
        raise ValueError(f"不存在模型：{model_id}") from error


def supports_request(
    model: VideoModelProfile,
    request: VideoRequest,
) -> bool:
    return (
        request.mode in model.supported_modes
        and model.min_duration_seconds <= request.duration_seconds
        and request.duration_seconds <= model.max_duration_seconds
    )
