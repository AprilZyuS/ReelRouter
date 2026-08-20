from langgraph.graph import END
from state import AgentState


def decide_next_agent(state: AgentState, max_retries: int) -> str:
    if not state.get("research"):
        return "researcher"

    if not state.get("answer"):
        return "writer"

    if not state.get("review_status"):
        return "reviewer"

    if state["review_status"] == "approved":
        return END

    if state["retry_count"] >= max_retries:
        return "human_review"

    return "writer"
