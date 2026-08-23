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
from video.approval_repository import (
    MySQLVideoApprovalRepository,
    PendingVideoApproval,
    VideoApprovalRepository,
)
from video.model_router import ModelSelection
from video.provider_factory import create_provider_bundle
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
    *,
    provider_name: str | None = None,
):
    """
    根据指定 Repository 创建一套完整的视频运行时。

    测试传入 InMemory Repository；
    生产环境传入 MySQL Repository。
    """
    bundle = create_provider_bundle(provider_name)
    service = VideoGenerationService(bundle.provider, repository, models=bundle.models)
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


@lru_cache
def get_video_approval_repository() -> VideoApprovalRepository:
    """保存高成本审批业务状态，使审批不依赖内存 Checkpoint。"""
    repository = MySQLVideoApprovalRepository(load_mysql_settings())
    repository.setup()
    return repository


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


def _approval_interrupt(approval: PendingVideoApproval) -> dict:
    return {
        "message": "该视频任务超过自动审批额度，需要人工确认。",
        "model_id": approval.model_id,
        "estimated_cost_usd": approval.estimated_cost_usd,
        "budget_usd": approval.request.budget_usd,
        "selection_reason": approval.selection_reason,
        "budget_reason": approval.budget_reason,
        "options": ["approve", "reject"],
    }


def _recover_pending_approval(
    approval: PendingVideoApproval,
    request: VideoApprovalRequest,
    service: VideoGenerationService,
    repository: VideoApprovalRepository,
) -> VideoWorkflowResponse:
    """在 LangGraph 内存状态丢失后，从 MySQL 继续一次审批。"""
    if approval.status == "submitted":
        job = service.repository.get(approval.job_id) if approval.job_id else None
        return VideoWorkflowResponse(
            thread_id=approval.thread_id,
            status="submitted",
            selection=ModelSelectionResponse(
                model_id=approval.model_id,
                estimated_cost_usd=approval.estimated_cost_usd,
                reason=approval.selection_reason,
            ),
            job=VideoJobStatusResponse.from_job(job) if job is not None else None,
            approval_status="approved",
        )
    if approval.status == "rejected":
        return VideoWorkflowResponse(
            thread_id=approval.thread_id,
            status="rejected",
            selection=ModelSelectionResponse(
                model_id=approval.model_id,
                estimated_cost_usd=approval.estimated_cost_usd,
                reason=approval.selection_reason,
            ),
            approval_status="rejected",
            error=approval.feedback or "用户拒绝执行该高成本视频任务。",
        )
    if approval.status != "awaiting":
        raise HTTPException(status_code=409, detail="审批任务状态无效。")

    feedback = request.feedback.strip()
    if request.action == "reject":
        rejected = PendingVideoApproval(
            **{**approval.__dict__, "status": "rejected", "feedback": feedback}
        )
        repository.save(rejected)
        return _recover_pending_approval(rejected, request, service, repository)

    model = next(
        (
            candidate
            for candidate in (service.models or ())
            if candidate.model_id == approval.model_id
        ),
        None,
    )
    if model is None:
        raise HTTPException(
            status_code=409,
            detail="审批时当前 Provider 不再提供当时选中的模型；拒绝自动提交。",
        )
    selection = ModelSelection(
        model=model,
        estimated_cost_usd=approval.estimated_cost_usd,
        reason=approval.selection_reason,
    )
    try:
        job = service.submit_selected(approval.request, selection)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=502, detail=f"提交 Provider 失败：{error}") from error
    submitted = PendingVideoApproval(
        **{
            **approval.__dict__,
            "status": "submitted",
            "feedback": feedback,
            "job_id": job.job_id,
        }
    )
    repository.save(submitted)
    return _recover_pending_approval(submitted, request, service, repository)


@router.post(
    "/jobs",
    response_model=VideoWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_video_job(
    request: VideoJobCreateRequest,
    response: Response,
    workflow=Depends(get_video_workflow),
    approval_repository: VideoApprovalRepository = Depends(
        get_video_approval_repository
    ),
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
        selection = workflow_response.selection
        if selection is None:
            raise RuntimeError("等待审批的视频任务缺少模型选择结果。")
        interrupt = workflow_response.interrupt or {}
        approval_repository.save(
            PendingVideoApproval(
                thread_id=thread_id,
                request=request.to_domain(),
                model_id=selection.model_id,
                estimated_cost_usd=selection.estimated_cost_usd,
                selection_reason=selection.reason,
                budget_reason=str(interrupt.get("budget_reason", "需要人工审批。")),
            )
        )
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
    service: VideoGenerationService = Depends(get_video_service),
    approval_repository: VideoApprovalRepository = Depends(
        get_video_approval_repository
    ),
) -> VideoWorkflowResponse:
    """恢复暂停的高成本任务，并执行用户批准或拒绝的决定。"""
    config = make_config(thread_id)
    snapshot = workflow.get_state(config)
    if not snapshot.values:
        approval = approval_repository.get(thread_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="不存在视频工作流任务。")
        return _recover_pending_approval(
            approval,
            request,
            service,
            approval_repository,
        )

    result = workflow.invoke(
        Command(
            resume={
                "action": request.action,
                "feedback": request.feedback,
            }
        ),
        config=config,
    )
    workflow_response = build_workflow_response(result, thread_id, workflow)
    if workflow_response.status == "failed":
        # 审批已通过但 Provider 拒绝提交时，保留审批记录为 awaiting，
        # 让用户修复配置/额度后可以安全重试；HTTP 层必须返回可读错误。
        raise HTTPException(status_code=502, detail=workflow_response.error)
    approval = approval_repository.get(thread_id)
    if approval is not None:
        approval_repository.save(
            PendingVideoApproval(
                **{
                    **approval.__dict__,
                    "status": (
                        "submitted"
                        if workflow_response.status == "submitted"
                        else "rejected"
                    ),
                    "feedback": request.feedback.strip(),
                    "job_id": (
                        workflow_response.job.job_id
                        if workflow_response.job is not None
                        else None
                    ),
                }
            )
        )
    return workflow_response


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
