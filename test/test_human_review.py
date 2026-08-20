from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from human_review import human_review
from routing import decide_next_agent
from workflow import build_graph


MAX_RETRIES = 2


def make_state():
    return {
        "task": "解释 Python 是什么",
        "research": "Python 是一种通用编程语言。",
        "answer": "这是一份尚未通过的答案。",
        "review_status": "needs_revision",
        "review_feedback": "需要补充具体示例。",
        "next_agent": "",
        "retry_count": MAX_RETRIES,
        "sources": [],
        "human_choice": "",
    }


def build_human_review_graph():
    checkpointer = InMemorySaver()

    def fake_researcher(state):
        return {"research": "测试研究结果。", "sources": []}

    def fake_writer(state):
        return {
            "answer": "根据人工意见修改后的答案。",
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

    graph = build_graph(
        fake_researcher,
        fake_writer,
        fake_reviewer,
        fake_supervisor,
        human_review,
        checkpointer=checkpointer,
    )
    return graph


def pause_at_human_review(graph, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(make_state(), config=config)
    return config, result


def test_human_review_pauses_after_retry_limit():
    graph = build_human_review_graph()
    _, result = pause_at_human_review(graph, "pause-test")

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["answer"] == "这是一份尚未通过的答案。"
    assert payload["review_feedback"] == "需要补充具体示例。"
    assert payload["options"] == ["continue", "accept", "end"]


def test_human_accept_ends_the_workflow():
    graph = build_human_review_graph()
    config, _ = pause_at_human_review(graph, "accept-test")

    result = graph.invoke(Command(resume={"action": "accept"}), config=config)

    assert result["human_choice"] == "accept"
    assert result["review_status"] == "approved"
    assert graph.get_state(config).next == ()


def test_human_continue_returns_to_writer_then_ends():
    graph = build_human_review_graph()
    config, _ = pause_at_human_review(graph, "continue-test")

    result = graph.invoke(
        Command(resume={"action": "continue", "feedback": "请补充一个例子。"}),
        config=config,
    )

    assert result["human_choice"] == "continue"
    assert result["answer"] == "根据人工意见修改后的答案。"
    assert result["review_status"] == "approved"
    assert result["retry_count"] == 0
    assert graph.get_state(config).next == ()


def test_human_end_terminates_the_workflow():
    graph = build_human_review_graph()
    config, _ = pause_at_human_review(graph, "end-test")

    result = graph.invoke(Command(resume={"action": "end"}), config=config)

    assert result["human_choice"] == "end"
    assert result["review_status"] == "needs_revision"
    assert graph.get_state(config).next == ()
