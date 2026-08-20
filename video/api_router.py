"""视频生成任务的 FastAPI 路由。"""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from langgraph.types import Command

from video.api_schemas import (
    ModelSelectionResponse,
    VideoApprovalRequest,
    VideoJobCreateRequest,
    VideoJobStatusResponse,
    VideoOutputReviewRequest,
    VideoWorkflowResponse,
)
from video.checkpoint import create_video_checkpointer
from video.providers.mock_provider import MockVideoProvider
from video.service import VideoGenerationService
from video.workflow import build_video_workflow
from functools import lru_cache

from video.mysql_config import load_mysql_settings
from video.repository import (
    MySQLVideoJobRepository,
    VideoJobRepository,
)



router = APIRouter(prefix="/video", tags=["video"])


def create_video_runtime(
    repository: VideoJobRepository,
):
    """
    根据指定 Repository 创建一套完整的视频运行时。

    测试传入 InMemory Repository；
    生产环境传入 MySQL Repository。
    """
    provider = MockVideoProvider()
    service = VideoGenerationService(provider, repository)
    checkpointer = create_video_checkpointer()
    workflow = build_video_workflow(
        service,
        checkpointer=checkpointer,
    )
    return service, workflow


@lru_cache
def get_default_video_runtime():
    """
    生产环境默认运行时。

    首次真正收到视频 API 请求时才创建：
    - 读取 MySQL 配置
    - 创建表
    - 构造 MySQL Repository
    """
    repository = MySQLVideoJobRepository(
        load_mysql_settings()
    )
    repository.setup()

    return create_video_runtime(repository)

def get_video_service() -> VideoGenerationService:
    """FastAPI 获取生产环境的视频 Service。"""
    service, _ = get_default_video_runtime()
    return service


def get_video_workflow():
    """FastAPI 获取生产环境的视频工作流。"""
    _, workflow = get_default_video_runtime()
    return workflow


def make_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def build_workflow_response(
    result: dict,
    thread_id: str,
    workflow,
) -> VideoWorkflowResponse:
    """读取 checkpoint 中的完整 State，并转换为稳定的 HTTP 响应。"""
    state = workflow.get_state(make_config(thread_id)).values

    interrupt_payload = None
    if "__interrupt__" in result:
        interrupt_payload = result["__interrupt__"][0].value

    error = state.get("error")
    approval_status = state.get("approval_status")
    if interrupt_payload is not None:
        workflow_status = "awaiting_human_review"
    elif approval_status == "rejected":
        workflow_status = "rejected"
    elif error:
        workflow_status = "failed"
    else:
        workflow_status = "submitted"

    selection = state.get("selection")
    job = state.get("job")
    return VideoWorkflowResponse(
        thread_id=thread_id,
        status=workflow_status,
        selection=(
            ModelSelectionResponse.from_selection(selection)
            if selection is not None
            else None
        ),
        job=VideoJobStatusResponse.from_job(job) if job is not None else None,
        approval_status=approval_status,
        error=error,
        interrupt=interrupt_payload,
    )


@router.post(
    "/jobs",
    response_model=VideoWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_video_job(
    request: VideoJobCreateRequest,
    response: Response,
    workflow=Depends(get_video_workflow),
) -> VideoWorkflowResponse:
    """创建视频工作流；高成本任务会暂停并等待人工审批。"""
    thread_id = str(uuid4())
    result = workflow.invoke(
        {"request": request.to_domain()},
        config=make_config(thread_id),
    )
    workflow_response = build_workflow_response(result, thread_id, workflow)

    if workflow_response.status == "failed":
        raise HTTPException(status_code=400, detail=workflow_response.error)
    if workflow_response.status == "awaiting_human_review":
        response.status_code = status.HTTP_202_ACCEPTED
    return workflow_response


@router.post(
    "/jobs/{thread_id}/approval",
    response_model=VideoWorkflowResponse,
)
def approve_video_job(
    thread_id: str,
    request: VideoApprovalRequest,
    workflow=Depends(get_video_workflow),
) -> VideoWorkflowResponse:
    """恢复暂停的高成本任务，并执行用户批准或拒绝的决定。"""
    config = make_config(thread_id)
    snapshot = workflow.get_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="不存在视频工作流任务。")

    result = workflow.invoke(
        Command(
            resume={
                "action": request.action,
                "feedback": request.feedback,
            }
        ),
        config=config,
    )
    return build_workflow_response(result, thread_id, workflow)


@router.post(
    "/jobs/{job_id}/output-review",
    response_model=VideoJobStatusResponse,
)
def review_video_output(
    job_id: str,
    request: VideoOutputReviewRequest,
    service: VideoGenerationService = Depends(get_video_service),
) -> VideoJobStatusResponse:
    """保存已完成视频的人类质量评审。"""
    try:
        job = service.review_completed_job(job_id, request.to_domain())
    except ValueError as error:
        if "不存在任务" in str(error):
            raise HTTPException(status_code=404, detail=str(error)) from error
        raise HTTPException(status_code=409, detail=str(error)) from error
    return VideoJobStatusResponse.from_job(job)


@router.get(
    "/jobs/{job_id}",
    response_model=VideoJobStatusResponse,
)
def get_video_job(
    job_id: str,
    service: VideoGenerationService = Depends(get_video_service),
) -> VideoJobStatusResponse:
    """异步查询已提交的视频任务状态。"""
    try:
        job = service.get_job(job_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return VideoJobStatusResponse.from_job(job)