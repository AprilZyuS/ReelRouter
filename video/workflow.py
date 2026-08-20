"""视频任务创建与人工审批的 LangGraph 工作流。"""

from langgraph.graph import END, START, StateGraph

from video.budget_guard import evaluate_budget
from video.human_review import human_review
from video.service import VideoGenerationService
from video.state import VideoWorkflowState


def build_video_workflow(
    service: VideoGenerationService,
    *,
    auto_approval_limit: float = 0.50,
    checkpointer=None,
):
    """
    创建视频任务的工作流。

    该 Graph 只负责“选择、治理、审批、提交”，提交后返回 queued 状态。
    轮询是独立的异步查询动作，不能在一次 HTTP 请求中循环等待完成。
    """

    def select_model(state: VideoWorkflowState) -> dict:
        """选择满足请求约束的最低成本模型，但不提交任务。"""
        try:
            selection = service.select_for_request(state["request"])
        except ValueError as error:
            return {"error": str(error)}

        return {"selection": selection}

    def run_budget_guard(state: VideoWorkflowState) -> dict:
        """决定已选模型自动执行、等待审批，还是拒绝。"""
        decision = evaluate_budget(
            state["request"],
            state["selection"],
            auto_approval_limit=auto_approval_limit,
        )

        update = {"budget_decision": decision}
        if decision.action == "reject":
            update["error"] = decision.reason
        return update

    def submit_job(state: VideoWorkflowState) -> dict:
        """提交已经自动批准或人工批准的模型选择。"""
        try:
            job = service.submit_selected(
                state["request"],
                state["selection"],
            )
        except ValueError as error:
            return {"error": str(error)}

        return {"job": job}

    def route_after_selection(state: VideoWorkflowState):
        if state.get("error"):
            return END
        return "budget_guard"

    def route_after_budget_guard(state: VideoWorkflowState):
        action = state["budget_decision"].action
        if action == "auto_approve":
            return "submit_job"
        if action == "needs_human_review":
            return "human_review"
        return END

    builder = StateGraph(VideoWorkflowState)
    builder.add_node("select_model", select_model)
    builder.add_node("budget_guard", run_budget_guard)
    builder.add_node("human_review", human_review)
    builder.add_node("submit_job", submit_job)

    builder.add_edge(START, "select_model")
    builder.add_conditional_edges(
        "select_model",
        route_after_selection,
        {"budget_guard": "budget_guard", END: END},
    )
    builder.add_conditional_edges(
        "budget_guard",
        route_after_budget_guard,
        {
            "submit_job": "submit_job",
            "human_review": "human_review",
            END: END,
        },
    )

    # submit_job 不等待视频完成；后续由 GET /video/jobs/{job_id} 轮询。
    builder.add_edge("submit_job", END)

    return builder.compile(checkpointer=checkpointer)
