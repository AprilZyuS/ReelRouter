from langgraph.graph import END

from routing import decide_next_agent


MAX_RETRIES = 2


def make_state():
    """返回一份尚未开始执行任务的默认 State。"""
    return {
        "task": "测试任务",
        "research": "",
        "answer": "",
        "review_status": "",
        "review_feedback": "",
        "next_agent": "",
        "retry_count": 0,
        "sources": [],
        "human_choice": "",
    }


def test_should_route_to_researcher_when_research_is_empty():
    state = make_state()

    next_agent = decide_next_agent(state, MAX_RETRIES)

    assert next_agent == "researcher"


def test_should_route_to_writer_when_research_exists_but_answer_is_empty():
    state = make_state()
    state["research"] = "Python 是一种通用编程语言。"

    next_agent = decide_next_agent(state, MAX_RETRIES)

    assert next_agent == "writer"


def test_should_route_to_reviewer_when_answer_exists_but_not_reviewed():
    state = make_state()
    state["research"] = "Python 是一种通用编程语言。"
    state["answer"] = "Python 是一种高级编程语言。"

    next_agent = decide_next_agent(state, MAX_RETRIES)

    assert next_agent == "reviewer"


def test_should_end_when_reviewer_approves_answer():
    state = make_state()
    state["research"] = "Python 是一种通用编程语言。"
    state["answer"] = "Python 是一种高级编程语言。"
    state["review_status"] = "approved"

    next_agent = decide_next_agent(state, MAX_RETRIES)

    assert next_agent == END


def test_should_route_to_writer_when_revision_is_needed_below_retry_limit():
    state = make_state()
    state["research"] = "Python 是一种通用编程语言。"
    state["answer"] = "Python 是一种高级编程语言。"
    state["review_status"] = "needs_revision"
    state["retry_count"] = 1

    next_agent = decide_next_agent(state, MAX_RETRIES)

    assert next_agent == "writer"


def test_should_end_when_revision_reaches_retry_limit():
    state = make_state()
    state["research"] = "Python 是一种通用编程语言。"
    state["answer"] = "Python 是一种高级编程语言。"
    state["review_status"] = "needs_revision"
    state["retry_count"] = MAX_RETRIES

    next_agent = decide_next_agent(state, MAX_RETRIES)

    assert next_agent == "human_review"
