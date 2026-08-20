from langgraph.graph import END
from langgraph.types import Command, interrupt

from state import AgentState

def human_review(state:AgentState):
    decision = interrupt({
        "message": "自动修改次数已用完，请选择下一步。",
        "answer": state["answer"],
        "review_feedback": state["review_feedback"],
        "options": ["continue", "accept", "end"],
    })

    action = decision["action"]

    if action == "continue":
        return Command(
            update={
                "human_choice": "continue",
                "review_status": "",
                "review_feedback": decision.get("feedback",""),
                "retry_count": 0
            },
            goto= "writer"
        )
    
    if action == "accept":
        return Command(
            update={
                "human_choice": "accept",
                "review_status": "approved"
            },
            goto= END
        )

    if action == "end":
        return Command(
            update={
                "human_choice": "end"
            },
            goto=END
        )

    raise ValueError("action 必须是 continue、accept 或 end。")
