from langgraph.checkpoint.memory import InMemorySaver

from routing import decide_next_agent
from workflow import build_graph


MAX_RETRIES = 2


def make_initial_state(task: str = "解释 Python 是什么"):
    return {
        "task": task,
        "research": "",
        "answer": "",
        "review_status": "",
        "review_feedback": "",
        "next_agent": "",
        "retry_count": 0,
        "sources": [],
        "human_choice": "",
    }


def build_test_graph():
    checkpointer = InMemorySaver()

    def fake_researcher(state):
        return {
            "research": f"关于『{state['task']}』的测试研究结果。",
            "sources": [{"title": "测试来源", "url": "https://example.com"}],
        }

    def fake_writer(state):
        return {
            "answer": f"根据研究结果生成的答案：{state['research']}",
            "review_status": "",
            "review_feedback": "",
        }

    def fake_reviewer(state):
        return {
            "review_status": "approved",
            "review_feedback": "",
            "retry_count": state["retry_count"],
        }

    def fake_supervisor(state):
        next_agent = decide_next_agent(state, max_retries=MAX_RETRIES)
        return {"next_agent": next_agent}

    def fake_human_review(state):
        return {"human_choice": "end"}

    graph = build_graph(
        fake_researcher,
        fake_writer,
        fake_reviewer,
        fake_supervisor,
        fake_human_review,
        checkpointer=checkpointer,
    )
    return graph


def test_checkpointer_saves_final_state_for_thread():
    graph = build_test_graph()
    config = {"configurable": {"thread_id": "checkpoint-final-state"}}

    graph.invoke(make_initial_state(), config=config)
    snapshot = graph.get_state(config)

    assert snapshot.values["task"] == "解释 Python 是什么"
    assert snapshot.values["review_status"] == "approved"
    assert snapshot.values["retry_count"] == 0
    assert snapshot.next == ()


def test_checkpointer_keeps_multiple_state_snapshots():
    graph = build_test_graph()
    config = {"configurable": {"thread_id": "checkpoint-history"}}

    graph.invoke(make_initial_state(), config=config)
    history = list(graph.get_state_history(config))

    assert len(history) > 1
    assert history[0].values["review_status"] == "approved"
    assert history[0].next == ()


def test_checkpointer_keeps_different_threads_isolated():
    graph = build_test_graph()
    python_config = {"configurable": {"thread_id": "python-thread"}}
    vla_config = {"configurable": {"thread_id": "vla-thread"}}

    graph.invoke(make_initial_state("调研 Python"), config=python_config)
    graph.invoke(make_initial_state("调研 VLA"), config=vla_config)

    python_snapshot = graph.get_state(python_config)
    vla_snapshot = graph.get_state(vla_config)

    assert python_snapshot.values["task"] == "调研 Python"
    assert vla_snapshot.values["task"] == "调研 VLA"
    assert python_snapshot.values["research"] != vla_snapshot.values["research"]
