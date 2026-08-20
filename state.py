from typing import Literal, TypedDict


class AgentState(TypedDict):
    task: str
    research: str
    answer: str
    review_status: Literal["", "approved", "needs_revision"]
    review_feedback: str
    next_agent: str
    retry_count: int
    sources: list[dict[str, str]]
    human_choice: Literal["","continue","accept","end"]

