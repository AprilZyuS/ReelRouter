from typing import Literal
from uuid import uuid4
from functools import lru_cache
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from langgraph.types import Command
from video.api_router import router as video_router

app = FastAPI(
    title="ReelRouter",
    description="AI 视频生成编排与成本优化平台原型。",
    version="0.1.0",
)

# 浏览器前端与 FastAPI 在开发环境使用不同端口；明确列出可信来源，
# 不使用允许任意来源的 CORS 配置。
_default_web_origins = "http://127.0.0.1:5173,http://localhost:5173"
_web_origins = [
    origin.strip()
    for origin in os.getenv("WEB_ALLOWED_ORIGINS", _default_web_origins).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_web_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(video_router)


@lru_cache
def get_research_graph():
    """旧版调研练习仅在调用 /research 时加载，不能阻断视频 API 启动。"""
    from graph import graph

    return graph

class ResearchRequest(BaseModel):
    task: str = Field(
        min_length=1,
        max_length=1000,
        description="需要调研的问题"
    )

class ResumeRequest(BaseModel):
    action : Literal["continue","accept","end"]
    feedback:str = ""

class SourceResponse(BaseModel):
    title : str
    url : str
    snippet : str

class ResearchResponse(BaseModel):
    thread_id: str
    status: Literal["completed", "awaiting_human_review"]
    answer: str
    research: str
    review_status: str
    review_feedback: str
    retry_count: int
    sources: list[SourceResponse]
    human_choice: str
    interrupt: dict | None = None

def build_response(result, thread_id: str, graph) -> ResearchResponse:
    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    snapshot = graph.get_state(config)
    state = snapshot.values

    interrupt_payload = None
    status = "completed"

    if "__interrupt__" in result:
        status = "awaiting_human_review"
        interrupt_payload = result["__interrupt__"][0].value

    return ResearchResponse(
        thread_id=thread_id,
        status=status,
        answer=state.get("answer", ""),
        research=state.get("research", ""),
        review_status=state.get("review_status", ""),
        review_feedback=state.get("review_feedback", ""),
        retry_count=state.get("retry_count", 0),
        sources=state.get("sources", []),
        human_choice=state.get("human_choice", ""),
        interrupt=interrupt_payload,
    )


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/research", response_model=ResearchResponse)
def research(request: ResearchRequest):
    thread_id = str(uuid4())

    config = {
        "configurable": {
            "thread_id": thread_id,
        },
        "recursion_limit": 20,
    }

    initial_state = {
        "task": request.task,
        "research": "",
        "answer": "",
        "review_status": "",
        "review_feedback": "",
        "next_agent": "",
        "retry_count": 0,
        "sources": [],
        "human_choice": "",
    }

    graph = get_research_graph()
    result = graph.invoke(initial_state, config=config)

    return build_response(result, thread_id, graph)

@app.post(
    "/research/{thread_id}/resume",
    response_model=ResearchResponse,
)
def resume_research(thread_id: str, request: ResumeRequest):
    config = {
        "configurable": {
            "thread_id": thread_id,
        },
        "recursion_limit": 20,
    }

    graph = get_research_graph()
    result = graph.invoke(
        Command(
            resume={
                "action": request.action,
                "feedback": request.feedback,
            }
        ),
        config=config,
    )

    return build_response(result, thread_id, graph)
