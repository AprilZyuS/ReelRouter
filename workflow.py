from langgraph.graph import END, START, StateGraph

from routes import route_supervisor
from state import AgentState


def build_graph(researcher, writer, reviewer, supervisor, human_review, checkpointer=None):
    builder = StateGraph(AgentState)

    builder.add_node("researcher", researcher)
    builder.add_node("writer", writer)
    builder.add_node("reviewer", reviewer)
    builder.add_node("supervisor", supervisor)
    builder.add_node("human_review", human_review)

    builder.add_edge(START, "supervisor")
    builder.add_edge("researcher", "supervisor")
    builder.add_edge("writer", "supervisor")
    builder.add_edge("reviewer", "supervisor")

    builder.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "researcher": "researcher",
            "writer": "writer",
            "reviewer": "reviewer",
            "human_review": "human_review",
            END: END,
            
        },
    )

    return builder.compile(checkpointer=checkpointer)
