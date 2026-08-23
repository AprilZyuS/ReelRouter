import pytest

from narrative.schemas import (
    NarrativeProjectProfile,
    PrioritizedShot,
    PrioritizedStoryboard,
    ShotImportance,
)
from narrative.video_execution import (
    EpisodeBudgetExceeded,
    EpisodePartialSubmissionError,
    EpisodeVideoExecutor,
    InMemoryShotVideoTaskStore,
    VideoExecutionApprovalRequired,
)
from narrative.visual_assets import ShotReferenceAsset
from video.model_registry import list_models
from video.providers.mock_provider import MockVideoProvider
from video.repository import InMemoryVideoJobRepository
from video.service import VideoGenerationService


def make_profile(*, budget: float = 1.0) -> NarrativeProjectProfile:
    return NarrativeProjectProfile(
        project_id="episode-video-demo",
        manuscript_document_id="manuscript-v1",
        title="测试项目",
        logline="用于测试逐镜头视频执行。",
        style_bible="冷色调悬疑电影感。",
        planned_episode_count=2,
        keywords=["测试"],
        genre="悬疑",
        episode_duration_seconds=15,
        episode_budget_usd=budget,
    )


def make_storyboard() -> PrioritizedStoryboard:
    durations = [2, 2, 2, 3, 3, 3]
    shots = [
        PrioritizedShot(
            shot_id=f"shot-{index}",
            scene_id=f"scene-{index}",
            order=index,
            visual_prompt=f"测试画面 {index}",
            camera_instruction="中景，缓慢推进。",
            duration_seconds=duration,
            source_chunk_ids=["chunk-1"],
            importance=(ShotImportance.KEY if index == 1 else ShotImportance.STANDARD),
            priority_reason="开场关键镜头" if index == 1 else "普通叙事镜头",
            min_quality_score=7 if index == 1 else 5,
        )
        for index, duration in enumerate(durations, start=1)
    ]
    return PrioritizedStoryboard(
        project_id="episode-video-demo",
        episode_number=1,
        target_duration_seconds=15,
        shots=shots,
    )


def make_executor() -> tuple[EpisodeVideoExecutor, InMemoryShotVideoTaskStore]:
    task_store = InMemoryShotVideoTaskStore()
    service = VideoGenerationService(
        MockVideoProvider(),
        InMemoryVideoJobRepository(),
        models=tuple(list_models(provider="mock")),
    )
    return EpisodeVideoExecutor(service, task_store), task_store


def test_budget_is_checked_for_the_whole_episode_before_any_submission():
    executor, task_store = make_executor()

    # 每个镜头单独看都可支付，但合计超出本集预算。
    with pytest.raises(EpisodeBudgetExceeded, match="未提交任何视频任务"):
        executor.build_plan(make_profile(budget=0.15), make_storyboard())

    assert task_store.list_episode("episode-video-demo", 1) == []


def test_reference_asset_guard_requires_every_shot_to_be_bound():
    executor, _ = make_executor()
    assets = {
        "shot-1": ShotReferenceAsset(
            project_id="episode-video-demo",
            episode_number=1,
            shot_id="shot-1",
            asset_id="lin-xiao-v1",
            asset_version=1,
            reference_image_url="https://assets.example/lin-xiao-v1.png",
        )
    }

    with pytest.raises(ValueError, match="每个镜头都必须绑定"):
        executor.build_plan(
            make_profile(),
            make_storyboard(),
            reference_assets=assets,
            require_reference_assets=True,
        )


def test_submit_links_each_shot_and_can_poll_until_terminal():
    executor, task_store = make_executor()
    assets = {
        f"shot-{index}": ShotReferenceAsset(
            project_id="episode-video-demo",
            episode_number=1,
            shot_id=f"shot-{index}",
            asset_id="lin-xiao-v1",
            asset_version=1,
            reference_image_url="https://assets.example/lin-xiao-v1.png",
        )
        for index in range(1, 7)
    }
    plan = executor.build_plan(
        make_profile(),
        make_storyboard(),
        reference_assets=assets,
        require_reference_assets=True,
    )

    assert all(item.request.mode.value == "image_to_video" for item in plan.shots)
    with pytest.raises(VideoExecutionApprovalRequired):
        executor.submit_plan(plan, confirmed=False)

    links = executor.submit_plan(plan, confirmed=True)
    assert len(links) == 6
    assert all(link.reference_asset_id == "lin-xiao-v1" for link in links)
    assert task_store.list_episode("episode-video-demo", 1) == links

    executor.poll_episode("episode-video-demo", 1)
    completed = executor.poll_episode("episode-video-demo", 1)
    assert executor.is_terminal(completed)
    assert all(job.output_url for job in completed)


def test_partial_provider_failure_can_resume_without_duplicate_submissions():
    class FailAfterTwoSubmissions(MockVideoProvider):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def submit(self, request, model):
            self.calls += 1
            if self.calls > 2:
                raise RuntimeError("模拟 Provider 临时失败")
            return super().submit(request, model)

    repository = InMemoryVideoJobRepository()
    task_store = InMemoryShotVideoTaskStore()
    failing_service = VideoGenerationService(
        FailAfterTwoSubmissions(),
        repository,
        models=tuple(list_models(provider="mock")),
    )
    plan = EpisodeVideoExecutor(failing_service, task_store).build_plan(
        make_profile(), make_storyboard()
    )

    with pytest.raises(EpisodePartialSubmissionError) as error:
        EpisodeVideoExecutor(failing_service, task_store).submit_plan(
            plan, confirmed=True
        )
    assert len(error.value.links) == 2
    existing_ids = {link.video_job_id for link in error.value.links}

    healthy_service = VideoGenerationService(
        MockVideoProvider(),
        repository,
        models=tuple(list_models(provider="mock")),
    )
    resumed_links = EpisodeVideoExecutor(healthy_service, task_store).submit_plan(
        plan, confirmed=True
    )

    assert len(resumed_links) == 6
    assert {link.video_job_id for link in resumed_links[:2]} == existing_ids
