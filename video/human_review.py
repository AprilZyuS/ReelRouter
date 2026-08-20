"""高成本视频任务的人工审批节点。"""

from langgraph.graph import END
from langgraph.types import Command, interrupt

from video.state import VideoWorkflowState


def human_review(state: VideoWorkflowState) -> Command:
    """
    暂停高成本任务，等待用户决定是否允许真正提交给 Provider。

    此节点只处理授权，不负责重新选择模型，也不负责提交任务。
    """
    selection = state["selection"]
    decision = state["budget_decision"]

    response = interrupt(
        {
            "message": "该视频任务超过自动审批额度，需要人工确认。",
            "model_id": selection.model.model_id,
            "estimated_cost_usd": selection.estimated_cost_usd,
            "budget_usd": state["request"].budget_usd,
            "selection_reason": selection.reason,
            "budget_reason": decision.reason,
            "options": ["approve", "reject"],
        }
    )

    action = response["action"]
    feedback = response.get("feedback", "").strip()

    if action == "approve":
        return Command(
            update={
                "approval_status": "approved",
                "approval_feedback": feedback,
            },
            goto="submit_job",
        )

    if action == "reject":
        return Command(
            update={
                "approval_status": "rejected",
                "approval_feedback": feedback,
                "error": feedback or "用户拒绝执行该高成本视频任务。",
            },
            goto=END,
        )

    raise ValueError("action 必须是 approve 或 reject。")
