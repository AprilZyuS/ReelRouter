"""长文本分集创作工作流的 FastAPI 接口。

该路由只负责把既有领域服务暴露给前端：小说、分集、剧本、审查、分镜与整集
视频执行仍分别由独立的领域对象完成，不能在路由内重新实现业务规则。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from narrative.ark_story_writer import ArkConfigurationError, ArkResponseError, ArkStoryWriterClient
from narrative.episode_planner import EpisodePlanner, EpisodePlannerOutputError
from narrative.priority_agent import PriorityAgent
from narrative.runtime import NarrativeRuntime, create_narrative_runtime
from narrative.schemas import (
    EpisodePlan,
    NarrativeProjectProfile,
    NarrativeProjectRequest,
    PrioritizedStoryboard,
    ScreenplayCandidate,
)
from narrative.screenplay_reviewer import ScreenplayReviewer, ScreenplayReviewOutputError
from narrative.screenwriter import Screenwriter, ScreenwriterOutputError
from narrative.storyboard_writer import (
    StoryboardOutputError,
    StoryboardVideoConstraints,
    StoryboardWriter,
)
from narrative.video_execution import (
    EpisodeBudgetExceeded,
    EpisodePartialSubmissionError,
    EpisodeVideoExecutor,
    VideoExecutionApprovalRequired,
)
from narrative.video_task_repository import MySQLShotVideoTaskStore
from narrative.visual_assets import MySQLShotReferenceAssetStore
from video.api_router import get_video_service
from video.api_schemas import VideoJobStatusResponse
from video.mysql_config import load_mysql_settings
from video.service import VideoGenerationService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix="/narrative", tags=["narrative-production"])


class CreateNarrativeProjectRequest(BaseModel):
    """用户用关键词创建一个长文本分集项目的输入。"""

    project_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    keywords: list[str] = Field(min_length=1, max_length=8)
    genre: str = Field(min_length=1, max_length=80)
    visual_style: str = Field(min_length=1, max_length=200)
    episode_duration_seconds: int = Field(ge=15, le=60)
    episode_budget_usd: float = Field(gt=0)
    enable_assembly: bool = True
    confirm_paid_call: bool = False

    def to_domain(self) -> NarrativeProjectRequest:
        return NarrativeProjectRequest(
            **self.model_dump(exclude={"confirm_paid_call"})
        )


class PaidCallRequest(BaseModel):
    """每次可能调用创作模型的操作都必须由 UI 明确确认。"""

    confirm_paid_call: bool = False


class EpisodePlanRequest(PaidCallRequest):
    episode_count: int = Field(default=2, ge=1, le=20)


class EpisodeNumberRequest(PaidCallRequest):
    episode_number: int = Field(default=1, ge=1)


class CandidateIdRequest(PaidCallRequest):
    candidate_id: str = Field(min_length=1, max_length=64)


class HumanApproveRequest(BaseModel):
    confirm_human_approval: bool = False


class EpisodeVideoExecutionRequest(BaseModel):
    """整集视频提交必须单独确认，避免把 LLM 调用与视频费用混为一谈。"""

    confirm_video_execution: bool = False
    require_reference_assets: bool = False


def _model_dump(value: object) -> dict:
    """将已有 Pydantic 领域对象稳定地转换为 JSON 响应。"""

    return value.model_dump(mode="json")  # type: ignore[union-attr]


@lru_cache
def get_narrative_runtime() -> NarrativeRuntime:
    """生产运行时：延迟创建，避免 API 启动即加载模型或产生 LLM 调用。"""

    return create_narrative_runtime(
        index_root=PROJECT_ROOT / "data" / "narrative_indexes",
    )


def _require_paid_confirmation(confirmed: bool) -> None:
    if not confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="此步骤会调用创作模型；请勾选确认后再执行。",
        )


def _episode(runtime: NarrativeRuntime, project_id: str, episode_number: int) -> EpisodePlan:
    episode = next(
        (
            plan
            for plan in runtime.repository.list_episode_plans(project_id)
            if plan.episode_number == episode_number
        ),
        None,
    )
    if episode is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目没有已保存的第 {episode_number} 集计划。",
        )
    return episode


def _episode_readiness(runtime: NarrativeRuntime, plan: EpisodePlan) -> dict:
    """返回页面可展示的流程就绪状态，而不是让 UI 猜测各类长期记忆。"""

    previous_summary_ready = (
        plan.episode_number == 1
        or runtime.repository.get_episode_summary(
            plan.project_id, plan.episode_number - 1
        )
        is not None
    )
    block_reason = None
    if not previous_summary_ready:
        block_reason = (
            f"第 {plan.episode_number} 集需要先完成第 {plan.episode_number - 1} 集的 "
            "Reviewer 审查并人工批准，系统才会写入可供本集使用的连续性摘要。"
        )
    return {
        "episode_number": plan.episode_number,
        "screenplay_approved": runtime.repository.get_screenplay(
            plan.project_id, plan.episode_number
        )
        is not None,
        "previous_episode_summary_ready": previous_summary_ready,
        "storyboard_ready": runtime.repository.get_prioritized_storyboard(
            plan.project_id, plan.episode_number
        )
        is not None,
        "screenplay_block_reason": block_reason,
    }


def _project_request(profile: NarrativeProjectProfile) -> NarrativeProjectRequest:
    """后续 Agent 只读取项目初始约束，不在路由层伪造关键词或预算。"""

    return NarrativeProjectRequest(
        project_id=profile.project_id,
        title=profile.title,
        keywords=profile.keywords,
        genre=profile.genre,
        visual_style=profile.style_bible,
        episode_duration_seconds=profile.episode_duration_seconds,
        episode_budget_usd=profile.episode_budget_usd,
        enable_assembly=profile.enable_assembly,
    )


def _raise_domain_error(error: Exception) -> None:
    """把可预期的配置、模型与业务错误转换为可读 HTTP 结果。"""

    if isinstance(error, ArkConfigurationError):
        raise HTTPException(status_code=503, detail=str(error)) from error
    if isinstance(error, ArkResponseError):
        raise HTTPException(status_code=502, detail=str(error)) from error
    if isinstance(error, LookupError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    # 422 只表示用户请求或当前项目状态不满足业务前提；LLM 返回的 JSON/契约
    # 无效属于上游模型响应失败，前端需要据此提示“可重试模型步骤”，不能误导为
    # 用户表单填写错误。
    if isinstance(error, (EpisodePlannerOutputError, ScreenwriterOutputError,
                          ScreenplayReviewOutputError, StoryboardOutputError)):
        raise HTTPException(status_code=502, detail=str(error)) from error
    if isinstance(error, (ValueError, EpisodeBudgetExceeded, VideoExecutionApprovalRequired)):
        raise HTTPException(status_code=422, detail=str(error)) from error
    if isinstance(error, EpisodePartialSubmissionError):
        raise HTTPException(status_code=502, detail=str(error)) from error
    raise error


def _video_executor(service: VideoGenerationService) -> EpisodeVideoExecutor:
    settings = load_mysql_settings()
    task_store = MySQLShotVideoTaskStore(settings)
    task_store.setup()
    return EpisodeVideoExecutor(service, task_store)


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(
    request: CreateNarrativeProjectRequest,
    runtime: NarrativeRuntime = Depends(get_narrative_runtime),
) -> dict:
    """关键词与创作约束 -> 小说正文 -> MySQL 分块与 FAISS 索引。"""

    _require_paid_confirmation(request.confirm_paid_call)
    try:
        result = runtime.generation_service.generate_and_ingest(request.to_domain())
    except Exception as error:
        _raise_domain_error(error)
    return {
        "profile": _model_dump(result.profile),
        "manuscript": _model_dump(result.manuscript),
        "document_id": result.document.document_id,
        "chunk_count": result.ingestion.chunk_count,
        "next_step": "规划分集",
    }


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    runtime: NarrativeRuntime = Depends(get_narrative_runtime),
) -> dict:
    profile = runtime.repository.get_project_profile(project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="项目不存在。")
    plans = runtime.repository.list_episode_plans(project_id)
    return {
        "profile": _model_dump(profile),
        "episodes": [_model_dump(plan) for plan in plans],
        "episode_readiness": [_episode_readiness(runtime, plan) for plan in plans],
    }


@router.post("/projects/{project_id}/episodes/plan")
def plan_episodes(
    project_id: str,
    request: EpisodePlanRequest,
    runtime: NarrativeRuntime = Depends(get_narrative_runtime),
) -> dict:
    """当前小说/RAG 证据 -> 连续分集计划，并写入项目当前版本。"""

    _require_paid_confirmation(request.confirm_paid_call)
    profile = runtime.repository.get_project_profile(project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="项目不存在。")
    try:
        plan_set = EpisodePlanner(ArkStoryWriterClient(), runtime.repository).plan(
            _project_request(profile), episode_count=request.episode_count
        )
        runtime.repository.save_episode_plan_set(plan_set)
    except Exception as error:
        _raise_domain_error(error)
    return {"project_id": project_id, "plans": [_model_dump(plan) for plan in plan_set.plans]}


@router.post("/projects/{project_id}/episodes/screenplay")
def write_screenplay(
    project_id: str,
    request: EpisodeNumberRequest,
    runtime: NarrativeRuntime = Depends(get_narrative_runtime),
) -> dict:
    """受控 Context Pack -> 候选剧本。候选稿不会自动发布。"""

    _require_paid_confirmation(request.confirm_paid_call)
    episode = _episode(runtime, project_id, request.episode_number)
    readiness = _episode_readiness(runtime, episode)
    if not readiness["previous_episode_summary_ready"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=readiness["screenplay_block_reason"],
        )
    try:
        context = runtime.context_manager.build(episode)
        screenplay = Screenwriter(ArkStoryWriterClient()).write(context)
        candidate = ScreenplayCandidate(candidate_id=f"sc-{uuid4().hex}", screenplay=screenplay)
        runtime.repository.save_screenplay_candidate(candidate)
    except Exception as error:
        _raise_domain_error(error)
    return {"candidate": _model_dump(candidate), "next_step": "Reviewer 审查，再人工批准"}


@router.post("/screenplay-candidates/{candidate_id}/review")
def review_screenplay(
    candidate_id: str,
    request: PaidCallRequest,
    runtime: NarrativeRuntime = Depends(get_narrative_runtime),
) -> dict:
    _require_paid_confirmation(request.confirm_paid_call)
    candidate = runtime.repository.get_screenplay_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="候选剧本不存在。")
    try:
        episode = _episode(runtime, candidate.screenplay.project_id, candidate.screenplay.episode_number)
        context = runtime.context_manager.build(episode)
        review = ScreenplayReviewer(ArkStoryWriterClient()).review(context, candidate.screenplay)
        stored = runtime.repository.record_screenplay_review(candidate_id, review)
    except Exception as error:
        _raise_domain_error(error)
    return {"candidate": _model_dump(stored)}


@router.get("/screenplay-candidates/{candidate_id}")
def get_screenplay_candidate(
    candidate_id: str,
    runtime: NarrativeRuntime = Depends(get_narrative_runtime),
) -> dict:
    """恢复页面时读取当前候选剧本及其 Reviewer 结论。"""

    candidate = runtime.repository.get_screenplay_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="候选剧本不存在。")
    return {"candidate": _model_dump(candidate)}


@router.post("/screenplay-candidates/{candidate_id}/approve")
def approve_screenplay(
    candidate_id: str,
    request: HumanApproveRequest,
    runtime: NarrativeRuntime = Depends(get_narrative_runtime),
) -> dict:
    """Reviewer 只能建议；该操作代表用户人工批准并写入跨集摘要。"""

    if not request.confirm_human_approval:
        raise HTTPException(status_code=400, detail="请确认已人工阅读剧本和 Reviewer 结论。")
    try:
        approved = runtime.repository.approve_screenplay_candidate(candidate_id)
    except Exception as error:
        _raise_domain_error(error)
    return {"candidate": _model_dump(approved), "next_step": "生成分镜与镜头优先级"}


@router.post("/projects/{project_id}/episodes/storyboard")
def create_storyboard(
    project_id: str,
    request: EpisodeNumberRequest,
    runtime: NarrativeRuntime = Depends(get_narrative_runtime),
    service: VideoGenerationService = Depends(get_video_service),
) -> dict:
    """已批准剧本 -> 6 至 12 个镜头 -> 确定性关键镜头优先级。"""

    _require_paid_confirmation(request.confirm_paid_call)
    episode = _episode(runtime, project_id, request.episode_number)
    screenplay = runtime.repository.get_screenplay(project_id, request.episode_number)
    if screenplay is None:
        raise HTTPException(status_code=409, detail="请先完成 Reviewer 审查并人工批准剧本。")
    try:
        context = runtime.context_manager.build(episode)
        constraints = StoryboardVideoConstraints.from_video_models(
            tuple(service.models or ()),
            target_duration_seconds=episode.target_duration_seconds,
        )
        storyboard = StoryboardWriter(ArkStoryWriterClient()).create(
            context,
            screenplay,
            video_constraints=constraints,
        )
        prioritized = PriorityAgent().prioritize(storyboard)
        runtime.repository.save_prioritized_storyboard(prioritized)
    except Exception as error:
        _raise_domain_error(error)
    return {"storyboard": _model_dump(prioritized), "next_step": "预检整集成本后提交视频"}


@router.get("/projects/{project_id}/episodes/{episode_number}/storyboard")
def get_storyboard(
    project_id: str,
    episode_number: int,
    runtime: NarrativeRuntime = Depends(get_narrative_runtime),
) -> dict:
    storyboard = runtime.repository.get_prioritized_storyboard(project_id, episode_number)
    if storyboard is None:
        raise HTTPException(status_code=404, detail="该集还没有已保存的优先级分镜。")
    return {"storyboard": _model_dump(storyboard)}


@router.post("/projects/{project_id}/episodes/{episode_number}/video-plan")
def preview_episode_video_plan(
    project_id: str,
    episode_number: int,
    request: EpisodeVideoExecutionRequest,
    runtime: NarrativeRuntime = Depends(get_narrative_runtime),
    service: VideoGenerationService = Depends(get_video_service),
) -> dict:
    """仅做成本与模型路由预检，不调用视频 Provider。"""

    profile = runtime.repository.get_project_profile(project_id)
    storyboard = runtime.repository.get_prioritized_storyboard(project_id, episode_number)
    if profile is None or storyboard is None:
        raise HTTPException(status_code=404, detail="需要项目 Profile 和已保存的优先级分镜。")
    try:
        settings = load_mysql_settings()
        assets = {
            asset.shot_id: asset
            for asset in MySQLShotReferenceAssetStore(settings).list_episode(project_id, episode_number)
        }
        plan = _video_executor(service).build_plan(
            profile, storyboard, reference_assets=assets,
            require_reference_assets=request.require_reference_assets,
        )
    except Exception as error:
        _raise_domain_error(error)
    return {
        "project_id": plan.project_id,
        "episode_number": plan.episode_number,
        "estimated_total_usd": plan.estimated_total_usd,
        "episode_budget_usd": plan.episode_budget_usd,
        "shots": [
            {
                "shot_id": item.shot_id,
                "model_id": item.selection.model.model_id,
                "estimated_cost_usd": item.selection.estimated_cost_usd,
                "mode": item.request.mode.value,
                "prompt": item.request.prompt,
                "importance": next(shot.importance.value for shot in storyboard.shots if shot.shot_id == item.shot_id),
            }
            for item in plan.shots
        ],
    }


@router.post("/projects/{project_id}/episodes/{episode_number}/videos")
def execute_episode_videos(
    project_id: str,
    episode_number: int,
    request: EpisodeVideoExecutionRequest,
    runtime: NarrativeRuntime = Depends(get_narrative_runtime),
    service: VideoGenerationService = Depends(get_video_service),
) -> dict:
    """在用户确认后，按优先级分镜提交整集异步视频任务。"""

    profile = runtime.repository.get_project_profile(project_id)
    storyboard = runtime.repository.get_prioritized_storyboard(project_id, episode_number)
    if profile is None or storyboard is None:
        raise HTTPException(status_code=404, detail="需要项目 Profile 和已保存的优先级分镜。")
    try:
        settings = load_mysql_settings()
        assets = {
            asset.shot_id: asset
            for asset in MySQLShotReferenceAssetStore(settings).list_episode(project_id, episode_number)
        }
        executor = _video_executor(service)
        plan = executor.build_plan(profile, storyboard, reference_assets=assets,
                                   require_reference_assets=request.require_reference_assets)
        links = executor.submit_plan(plan, confirmed=request.confirm_video_execution)
    except Exception as error:
        _raise_domain_error(error)
    return {"estimated_total_usd": plan.estimated_total_usd, "links": [link.__dict__ for link in links]}


@router.get("/projects/{project_id}/episodes/{episode_number}/videos")
def poll_episode_videos(
    project_id: str,
    episode_number: int,
    service: VideoGenerationService = Depends(get_video_service),
) -> dict:
    """查询整集镜头任务；未结束任务会由 Provider 刷新一次状态。"""

    try:
        jobs = _video_executor(service).poll_episode(project_id, episode_number)
    except Exception as error:
        _raise_domain_error(error)
    return {
        "jobs": [VideoJobStatusResponse.from_job(job).model_dump(mode="json") for job in jobs],
        "terminal": EpisodeVideoExecutor.is_terminal(jobs),
    }
