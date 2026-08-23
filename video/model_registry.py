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

# 真实模型仍以保守的估算参数参与 Router；价格和能力应按供应商套餐定期校准。
RUNWAY_MODELS = {
    "runway-gen4.5": VideoModelProfile(
        model_id="runway-gen4.5",
        provider="runway",
        supported_modes=frozenset(
            {GenerationMode.TEXT_TO_VIDEO, GenerationMode.IMAGE_TO_VIDEO}
        ),
        cost_per_second=0.12,
        estimated_latency_seconds=60,
        quality_score=9,
        min_duration_seconds=2,
        max_duration_seconds=10,
    ),
}


def build_seedance_model(*, cost_per_second: float) -> VideoModelProfile:
    """构造 Seedance 2.x 的运行时模型档案。

    Seedance 的真实计费以方舟控制台和任务 usage 为准；这里的价格仅用于
    在发起付费请求前执行预算护栏，必须由运行环境显式提供。
    """
    return VideoModelProfile(
        model_id="seedance-2.x",
        provider="seedance",
        supported_modes=frozenset(
            {GenerationMode.TEXT_TO_VIDEO, GenerationMode.IMAGE_TO_VIDEO}
        ),
        cost_per_second=cost_per_second,
        estimated_latency_seconds=90,
        quality_score=8,
        min_duration_seconds=4,
        max_duration_seconds=15,
    )


def list_models(*, provider: str | None = None) -> list[VideoModelProfile]:
    """列出指定 Provider 可执行的模型；默认保持 Mock 开发体验。"""
    if provider is None or provider == "mock":
        return list(MODELS.values())
    if provider == "runway":
        return list(RUNWAY_MODELS.values())
    if provider == "seedance":
        raise ValueError(
            "Seedance 模型档案需要运行时预算配置；"
            "请通过 create_provider_bundle('seedance') 获取。"
        )
    raise ValueError(f"不支持的视频 Provider：{provider}")


def get_model(model_id: str) -> VideoModelProfile:
    try:
        return MODELS[model_id]
    except KeyError:
        try:
            return RUNWAY_MODELS[model_id]
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
