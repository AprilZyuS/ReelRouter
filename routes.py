from state import AgentState


def route_supervisor(state: AgentState):
    return state["next_agent"]
