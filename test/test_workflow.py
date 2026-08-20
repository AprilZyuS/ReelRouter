from langgraph.graph import END
from langgraph.types import Command

from routing import decide_next_agent
from workflow import build_graph


MAX_RETRIES = 2


def make_initial_state():
    return {
        "task": "解释 Python 是什么",
        "research": "",
        "answer": "",
        "review_status": "",
        "review_feedback": "",
        "next_agent": "",
        "retry_count": 0,
        "sources": [],
        "human_choice": "",
    }


def fake_researcher(state):
    return {
        "research": "Python 是一种通用编程语言。",
        "sources": [{"title": "测试来源", "url": "https://example.com"}],
    }


def fake_supervisor(state):
    next_agent = decide_next_agent(state, max_retries=MAX_RETRIES)
    return {"next_agent": next_agent}


def fake_human_review(state):
    return Command(update={"human_choice": "end"}, goto=END)


def test_workflow_ends_when_reviewer_approves_first_draft():
    def fake_writer(state):
        return {
            "answer": "第一版答案。",
            "review_status": "",
            "review_feedback": "",
        }

    def fake_reviewer(state):
        return {
            "review_status": "approved",
            "review_feedback": "",
            "retry_count": state["retry_count"],
        }

    graph = build_graph(
        fake_researcher,
        fake_writer,
        fake_reviewer,
        fake_supervisor,
        fake_human_review,
    )
    result = graph.invoke(make_initial_state(), config={"recursion_limit": 20})

    assert result["research"] == "Python 是一种通用编程语言。"
    assert result["answer"] == "第一版答案。"
    assert result["review_status"] == "approved"
    assert result["retry_count"] == 0
    assert result["next_agent"] == END


def test_workflow_rewrites_once_then_ends():
    def fake_writer(state):
        answer = "修订后的答案。" if state["retry_count"] == 1 else "第一版答案。"
        return {
            "answer": answer,
            "review_status": "",
            "review_feedback": "",
        }

    def fake_reviewer(state):
        if state["retry_count"] == 0:
            return {
                "review_status": "needs_revision",
                "review_feedback": "请补充细节。",
                "retry_count": 1,
            }

        return {
            "review_status": "approved",
            "review_feedback": "",
            "retry_count": state["retry_count"],
        }

    graph = build_graph(
        fake_researcher,
        fake_writer,
        fake_reviewer,
        fake_supervisor,
        fake_human_review,
    )
    result = graph.invoke(make_initial_state(), config={"recursion_limit": 20})

    assert result["answer"] == "修订后的答案。"
    assert result["review_status"] == "approved"
    assert result["retry_count"] == 1
    assert result["next_agent"] == END


def test_workflow_ends_after_reaching_retry_limit():
    def fake_writer(state):
        return {
            "answer": "仍需修改的答案。",
            "review_status": "",
            "review_feedback": "",
        }

    def fake_reviewer(state):
        return {
            "review_status": "needs_revision",
            "review_feedback": "答案未达到要求。",
            "retry_count": state["retry_count"] + 1,
        }

    graph = build_graph(
        fake_researcher,
        fake_writer,
        fake_reviewer,
        fake_supervisor,
        fake_human_review,
    )
    result = graph.invoke(make_initial_state(), config={"recursion_limit": 20})

    assert result["review_status"] == "needs_revision"
    assert result["retry_count"] == MAX_RETRIES
    assert result["human_choice"] == "end"
