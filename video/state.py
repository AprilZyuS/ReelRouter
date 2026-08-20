from typing import Literal, NotRequired, TypedDict

from video.budget_guard import BudgetDecision
from video.model_router import ModelSelection
from video.schemas import VideoGenerationJob, VideoRequest


class VideoWorkflowState(TypedDict):
    """视频生成工作流在各节点之间传递的共享状态。"""

    # Graph 启动时必须提供的用户视频需求。
    request: VideoRequest

    # submit_job 成功后写入。
    selection: NotRequired[ModelSelection]

    # submit_job 成功后写入；后续由独立的异步查询接口更新任务状态。
    job: NotRequired[VideoGenerationJob]

    # 选型或提交失败时写入；存在时工作流应结束。
    error: NotRequired[str]

    # Budget Guard 的治理决定：自动执行、人工审批或拒绝。
    budget_decision: NotRequired[BudgetDecision]

    # 人工审批节点恢复后写入的最终授权结果。
    approval_status: NotRequired[Literal["approved", "rejected"]]

    # 用户在批准或拒绝时留下的补充说明。
    approval_feedback: NotRequired[str]
