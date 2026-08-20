from state import AgentState
from langchain_core.messages import HumanMessage, SystemMessage
from llm import llm
from review_parser import parse_review_response
from search_tool import mock_search
from citation_validator import validate_citations
from prompt import (
    RESEARCHER_SYSTEM_PROMPT,
    REVIEWER_SYSTEM_PROMPT,
    WRITER_SYSTEM_PROMPT,
)
from config import settings
from routing import decide_next_agent


def researcher(state: AgentState):
    print("Researcher is conducting research...")
    search_results = mock_search(state["task"])
    source_text = "\n".join(
    f"- {source['title']}: {source['snippet']} ({source['url']})"
    for source in search_results    
)
    response = llm.invoke([
        SystemMessage(content=RESEARCHER_SYSTEM_PROMPT),
        HumanMessage(content=f"研究任务：{state['task']}，请根据以下搜索结果提取研究内容：\n{source_text}"),
    ])
    return {"research": response.content, "sources": search_results}


def writer(state: AgentState):
    source_text = "\n".join(
    f"- {source['title']}: {source['url']}"
    for source in state["sources"]
)
    response = llm.invoke([
        SystemMessage(content=WRITER_SYSTEM_PROMPT),
        HumanMessage(
            content=f"用户任务：{state['task']}\n\n"
                    f"研究结果：\n{state['research']}\n\n"
                    f"上一版答案：\n{state['answer']}\n\n"
                    f"审稿意见：\n{state['review_feedback']}\n\n"
                    f"参考资料：\n{source_text}"
        ),
    ])

    return {
        "answer": response.content,
        "review_status": "",       # 新答案需要重新评审
        "review_feedback": "",     # 旧反馈已被 Writer 使用
    }

def reviewer(state: AgentState):
    response = llm.invoke([
        SystemMessage(content=REVIEWER_SYSTEM_PROMPT),
        HumanMessage(
            content=f"用户任务：{state['task']}\n\n"
                    f"待评审答案：\n{state['answer']}\n\n"
                    f"允许使用的参考资料：\n"
                    + "\n".join(
                        f"[{index}] {source['title']}: {source['url']}"
                        for index, source in enumerate(state["sources"], start=1)
                    )
        ),
    ])

    result = parse_review_response(response.content)
    status, feedback = result

    is_valid, citation_feedback = validate_citations(state["answer"], state["sources"])
    if not is_valid:
        status = "needs_revision"
        feedback += f"\n{citation_feedback}"

    retry_count = state["retry_count"]
    if status == "needs_revision":
        retry_count += 1



    return {
        "review_status": status,
        "review_feedback": feedback,
        "retry_count": retry_count  
    }

def supervisor(state: AgentState):
    print("Supervisor is deciding the next agent...")
    next_agent = decide_next_agent(
        state,
        settings.max_retries,
    )

    return {"next_agent": next_agent}
