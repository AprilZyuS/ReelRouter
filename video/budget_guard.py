"""视频任务的预算治理策略。"""

from dataclasses import dataclass
from typing import Literal

from video.model_router import ModelSelection
from video.schemas import VideoRequest


BudgetAction = Literal[
    "auto_approve",
    "needs_human_review",
    "reject",
]


@dataclass(frozen=True)
class BudgetDecision:
    """Budget Guard 对一次已选模型任务给出的执行决定。"""

    action: BudgetAction
    reason: str


def evaluate_budget(
    request: VideoRequest,
    selection: ModelSelection,
    auto_approval_limit: float = 0.50,
) -> BudgetDecision:
    """
    根据预估成本决定自动执行、人工审批或拒绝。

    Router 负责从候选模型中选出满足用户预算的最低成本模型；
    这里额外负责平台治理：即使任务不超过用户预算，超过自动审批额度时
    仍要求用户确认后才能真的调用 Provider。
    """
    if auto_approval_limit < 0:
        raise ValueError("auto_approval_limit 不能小于 0。")

    estimated_cost = selection.estimated_cost_usd

    # 这是防御性检查。正常情况下 Router 已过滤超预算模型；
    # 但 Guard 不能假设上游永远不会出现错误或被未来代码绕过。
    if estimated_cost > request.budget_usd:
        return BudgetDecision(
            action="reject",
            reason=(
                f"预计成本 ${estimated_cost:.2f} 超过用户预算 "
                f"${request.budget_usd:.2f}。"
            ),
        )

    if estimated_cost > auto_approval_limit:
        return BudgetDecision(
            action="needs_human_review",
            reason=(
                f"预计成本 ${estimated_cost:.2f} 未超过用户预算，"
                f"但高于自动审批额度 ${auto_approval_limit:.2f}，"
                "需要人工确认。"
            ),
        )

    return BudgetDecision(
        action="auto_approve",
        reason=(
            f"预计成本 ${estimated_cost:.2f} 在自动审批额度 "
            f"${auto_approval_limit:.2f} 内，可自动执行。"
        ),
    )
