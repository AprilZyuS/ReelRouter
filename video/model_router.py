from dataclasses import dataclass

# Costing 只负责算成本，不负责选择模型。
from video.costing import estimate_generation_cost

# Registry 提供全部模型资料，并负责判断模型是否技术兼容。
from video.model_registry import list_models, supports_request

# Router 只依赖视频领域数据，不依赖 Provider、Graph 或 LLM。
from video.schemas import VideoModelProfile, VideoRequest


@dataclass(frozen=True)
class ModelSelection:
    """
    Router 的选择结果。

    不只返回 model，额外返回预估成本和选择原因，
    这样 API、日志、前端和 Human Review 都能解释：
    “系统为什么选了这个模型？”
    """

    # 被 Router 选中的模型资料。
    model: VideoModelProfile

    # 基于本次时长计算出的预估生成成本。
    estimated_cost_usd: float

    # 给用户和开发者阅读的选择理由。
    reason: str


def select_model(request: VideoRequest) -> ModelSelection:
    """
    根据用户的视频需求，选择满足所有硬约束且成本最低的模型。

    当前 v1 的路由策略：

    1. 必须支持用户要求的生成模式；
    2. 必须支持用户要求的视频时长；
    3. 预计成本不能超过用户预算；
    4. 质量分不能低于用户最低要求；
    5. 在所有合格模型中，选择成本最低的。
    """

    # 第 1 层：能力筛选。
    #
    # 例如：
    # - 用户要 Image-to-Video；
    # - mock-economy 只支持 Text-to-Video；
    # - 因此 mock-economy 会在这里被淘汰。
    #
    # 时长超出模型 max_duration_seconds 的情况，
    # 也会在 supports_request() 中被淘汰。
    compatible_models = [
        model
        for model in list_models()
        if supports_request(model, request)
    ]

    # 如果一个模型都不兼容，继续判断预算没有意义。
    if not compatible_models:
        raise ValueError("没有模型支持当前生成模式或视频时长。")

    # 第 2 层：预算筛选。
    #
    # 此时只计算“技术上确实能完成请求”的模型成本，
    # 避免对本来就不能执行的模型进行无意义的成本计算。
    affordable_models = [
        (model, estimate_generation_cost(request, model))
        for model in compatible_models
        if estimate_generation_cost(request, model) <= request.budget_usd
    ]

    # 有模型能做，但用户预算不够。
    if not affordable_models:
        raise ValueError("没有模型满足当前预算。")

    # 第 3 层：质量筛选。
    #
    # min_quality_score 是用户的最低质量门槛，
    # 不是“系统必须选择全场最高质量模型”。
    quality_models = [
        (model, estimated_cost)
        for model, estimated_cost in affordable_models
        if model.quality_score >= request.min_quality_score
    ]

    # 预算足够，但所有可负担模型的质量都不达标。
    if not quality_models:
        raise ValueError("没有模型满足最低质量要求。")

    # 第 4 层：最终选择。
    #
    # 现在剩下的模型都已经：
    # - 技术兼容；
    # - 不超预算；
    # - 达到最低质量。
    #
    # 因此按成本从低到高选择第一个，
    # 这就是当前 v1 的“成本优化”策略。
    selected_model, estimated_cost = min(
        quality_models,
        key=lambda item: item[1],
    )

    # reason 是“可解释性”的一部分。
    # 不应该只告诉用户选了什么，还要告诉他为什么。
    reason = (
        f"选择 {selected_model.model_id}："
        f"预计成本 ${estimated_cost:.2f}，"
        f"质量分 {selected_model.quality_score}，"
        f"在满足能力、预算和最低质量要求的模型中成本最低。"
    )

    return ModelSelection(
        model=selected_model,
        estimated_cost_usd=estimated_cost,
        reason=reason,
    )