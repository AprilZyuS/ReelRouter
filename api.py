from typing import Literal
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field

from graph import graph
from langgraph.types import Command
from video.api_router import router as video_router

app = FastAPI(
    title="ReelRouter",
    description="AI 视频生成编排与成本优化平台原型。",
    version="0.1.0",
)

app.include_router(video_router)

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

def build_response(result, thread_id: str) -> ResearchResponse:
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

    result = graph.invoke(initial_state, config=config)

    return build_response(result, thread_id)

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

    result = graph.invoke(
        Command(
            resume={
                "action": request.action,
                "feedback": request.feedback,
            }
        ),
        config=config,
    )

    return build_response(result, thread_id)
