"""视频工作流的 Checkpointer 配置。"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


# VideoWorkflowState 中会进入 checkpoint 的自定义 dataclass 和 Enum。
# 显式白名单避免 LangGraph 在未来严格序列化模式下拒绝反序列化这些类型。
VIDEO_ALLOWED_MSGPACK_MODULES = [
    ("video.schemas", "GenerationMode"),
    ("video.schemas", "JobStatus"),
    ("video.schemas", "CostSource"),
    ("video.schemas", "CostRecord"),
    ("video.schemas", "VideoRequest"),
    ("video.schemas", "VideoModelProfile"),
    ("video.schemas", "VideoGenerationJob"),
    ("video.output_review", "VideoOutputReview"),
    ("video.model_router", "ModelSelection"),
    ("video.budget_guard", "BudgetDecision"),
]


def create_video_checkpointer() -> InMemorySaver:
    """创建能安全保存和恢复视频工作流 State 的内存 Checkpointer。"""
    serializer = JsonPlusSerializer(
        allowed_msgpack_modules=VIDEO_ALLOWED_MSGPACK_MODULES,
    )
    return InMemorySaver(serde=serializer)
