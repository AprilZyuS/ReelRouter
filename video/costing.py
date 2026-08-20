from video.model_registry import supports_request
from video.schemas import VideoModelProfile, VideoRequest


def estimate_generation_cost(
    request: VideoRequest,
    model: VideoModelProfile,
) -> float:
    """根据模型单价和视频时长计算预估成本。"""
    # Provider 只验证“这个模型能否执行请求”，不负责选择模型或判断预算。
    # 模型选择与预算策略会由后续的 Router / Budget Guard 负责。
    if not supports_request(model, request):
        raise ValueError("该模型不支持当前视频请求。")

    return round(request.duration_seconds * model.cost_per_second, 4)