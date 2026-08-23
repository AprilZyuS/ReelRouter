"""将已批准的优先级分镜转换为可恢复的视频生成任务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from narrative.schemas import NarrativeProjectProfile, PrioritizedStoryboard
from narrative.visual_assets import ShotReferenceAsset
from video.model_router import ModelSelection
from video.schemas import GenerationMode, JobStatus, VideoGenerationJob, VideoRequest
from video.service import VideoGenerationService


@dataclass(frozen=True)
class ShotVideoTaskLink:
    """一个叙事镜头与一个外部视频任务的稳定关联。"""

    project_id: str
    episode_number: int
    shot_id: str
    video_job_id: str
    model_id: str
    reference_asset_id: str | None = None


class ShotVideoTaskStore(Protocol):
    def setup(self) -> None: ...

    def save(self, link: ShotVideoTaskLink) -> None: ...

    def list_episode(
        self,
        project_id: str,
        episode_number: int,
    ) -> list[ShotVideoTaskLink]: ...


class InMemoryShotVideoTaskStore:
    def __init__(self) -> None:
        self._links: dict[tuple[str, int, str], ShotVideoTaskLink] = {}

    def setup(self) -> None:
        pass

    def save(self, link: ShotVideoTaskLink) -> None:
        self._links[(link.project_id, link.episode_number, link.shot_id)] = link

    def list_episode(self, project_id: str, episode_number: int) -> list[ShotVideoTaskLink]:
        return sorted(
            (
                link
                for link in self._links.values()
                if link.project_id == project_id and link.episode_number == episode_number
            ),
            key=lambda link: link.shot_id,
        )


@dataclass(frozen=True)
class PlannedShotVideo:
    shot_id: str
    request: VideoRequest
    selection: ModelSelection
    reference_asset_id: str | None = None


@dataclass(frozen=True)
class EpisodeExecutionPlan:
    project_id: str
    episode_number: int
    shots: tuple[PlannedShotVideo, ...]
    estimated_total_usd: float
    episode_budget_usd: float


class EpisodeBudgetExceeded(ValueError):
    """逐镜头合计成本超出该集预算，提交前必须失败。"""


class VideoExecutionApprovalRequired(PermissionError):
    """真实视频提交前要求显式的人类成本确认。"""


class EpisodePartialSubmissionError(RuntimeError):
    """Provider 在部分镜头提交后失败；已提交任务已持久化，不能盲目重发。"""

    def __init__(self, cause: Exception, links: list[ShotVideoTaskLink]) -> None:
        super().__init__(f"部分镜头已提交，后续提交失败：{cause}")
        self.links = tuple(links)


class EpisodeVideoExecutor:
    """预检整集预算后提交镜头，避免部分生成造成不可控费用。"""

    def __init__(
        self,
        video_service: VideoGenerationService,
        task_store: ShotVideoTaskStore,
    ) -> None:
        self.video_service = video_service
        self.task_store = task_store

    def build_plan(
        self,
        profile: NarrativeProjectProfile,
        storyboard: PrioritizedStoryboard,
        *,
        reference_image_url: str | None = None,
        reference_assets: Mapping[str, ShotReferenceAsset] | None = None,
        require_reference_assets: bool = False,
    ) -> EpisodeExecutionPlan:
        if (profile.project_id, profile.episode_duration_seconds) != (
            storyboard.project_id,
            storyboard.target_duration_seconds,
        ):
            raise ValueError("优先级分镜必须属于当前项目且时长与 Profile 一致。")

        asset_by_shot = dict(reference_assets or {})
        unexpected_asset_ids = sorted(set(asset_by_shot) - {shot.shot_id for shot in storyboard.shots})
        if unexpected_asset_ids:
            raise ValueError("参考资产包含当前分镜不存在的 shot_id：" + ", ".join(unexpected_asset_ids))
        if require_reference_assets:
            missing_assets = [
                shot.shot_id for shot in storyboard.shots if shot.shot_id not in asset_by_shot
            ]
            if missing_assets:
                raise ValueError(
                    "启用参考资产守卫时，每个镜头都必须绑定已批准参考图："
                    + ", ".join(missing_assets)
                )
        planned: list[PlannedShotVideo] = []
        for shot in storyboard.shots:
            asset = asset_by_shot.get(shot.shot_id)
            shot_reference_url = (
                asset.reference_image_url if asset is not None else reference_image_url
            )
            mode = (
                GenerationMode.IMAGE_TO_VIDEO
                if shot_reference_url is not None
                else GenerationMode.TEXT_TO_VIDEO
            )
            request = VideoRequest(
                prompt=self._compile_prompt(profile, shot.visual_prompt, shot.camera_instruction),
                mode=mode,
                duration_seconds=shot.duration_seconds,
                # Router 的单任务预算上限不能替代整集预算；整集在下方统一校验。
                budget_usd=profile.episode_budget_usd,
                reference_image_url=shot_reference_url,
                min_quality_score=shot.min_quality_score,
            )
            planned.append(
                PlannedShotVideo(
                    shot_id=shot.shot_id,
                    request=request,
                    selection=self.video_service.select_for_request(request),
                    reference_asset_id=asset.asset_id if asset is not None else None,
                )
            )

        estimated_total = sum(item.selection.estimated_cost_usd for item in planned)
        if estimated_total > profile.episode_budget_usd:
            raise EpisodeBudgetExceeded(
                f"第 {storyboard.episode_number} 集预估总成本 ${estimated_total:.2f} "
                f"超过单集预算 ${profile.episode_budget_usd:.2f}；未提交任何视频任务。"
            )
        return EpisodeExecutionPlan(
            project_id=storyboard.project_id,
            episode_number=storyboard.episode_number,
            shots=tuple(planned),
            estimated_total_usd=estimated_total,
            episode_budget_usd=profile.episode_budget_usd,
        )

    def submit_plan(
        self,
        plan: EpisodeExecutionPlan,
        *,
        confirmed: bool,
    ) -> list[ShotVideoTaskLink]:
        if not confirmed:
            raise VideoExecutionApprovalRequired(
                "视频执行会产生 Provider 费用；请显式确认后再提交。"
            )
        existing_by_shot = {
            link.shot_id: link
            for link in self.task_store.list_episode(
                plan.project_id, plan.episode_number
            )
        }
        planned_shot_ids = {item.shot_id for item in plan.shots}
        obsolete_shot_ids = sorted(set(existing_by_shot) - planned_shot_ids)
        if obsolete_shot_ids:
            raise ValueError(
                "该集已有不属于当前分镜版本的视频任务，拒绝混用："
                + ", ".join(obsolete_shot_ids)
            )

        links: list[ShotVideoTaskLink] = []
        for item in plan.shots:
            existing = existing_by_shot.get(item.shot_id)
            if existing is not None:
                if (
                    existing.model_id != item.selection.model.model_id
                    or existing.reference_asset_id != item.reference_asset_id
                ):
                    raise ValueError(
                        f"镜头 {item.shot_id} 已按不同模型或资产版本提交；"
                        "拒绝重复计费。"
                    )
                links.append(existing)
                continue
            try:
                job = self.video_service.submit_selected(item.request, item.selection)
            except Exception as error:
                raise EpisodePartialSubmissionError(error, links) from error
            link = ShotVideoTaskLink(
                project_id=plan.project_id,
                episode_number=plan.episode_number,
                shot_id=item.shot_id,
                video_job_id=job.job_id,
                model_id=job.model_id,
                reference_asset_id=item.reference_asset_id,
            )
            self.task_store.save(link)
            links.append(link)
        return links

    def poll_episode(
        self,
        project_id: str,
        episode_number: int,
    ) -> list[VideoGenerationJob]:
        """轮询该集已提交任务；Provider 状态由 VideoJobRepository 持久化。"""
        jobs = [
            self.video_service.get_job(link.video_job_id)
            for link in self.task_store.list_episode(project_id, episode_number)
        ]
        return jobs

    @staticmethod
    def is_terminal(jobs: list[VideoGenerationJob]) -> bool:
        return bool(jobs) and all(
            job.status in {JobStatus.COMPLETED, JobStatus.FAILED} for job in jobs
        )

    @staticmethod
    def _compile_prompt(
        profile: NarrativeProjectProfile,
        visual_prompt: str,
        camera_instruction: str,
    ) -> str:
        return (
            f"{profile.style_bible}\n"
            f"画面：{visual_prompt}\n"
            f"镜头：{camera_instruction}\n"
            "保持同一集的角色、服装、场景和色彩设定连续；不要新增未在分镜中出现的剧情。"
        )
