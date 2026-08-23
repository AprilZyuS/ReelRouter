import pytest

from narrative.assembly import EpisodeAssemblyNotReady, build_episode_assembly_plan
from narrative.schemas import (
    PrioritizedShot,
    PrioritizedStoryboard,
    ShotImportance,
)
from narrative.video_execution import ShotVideoTaskLink
from video.output_review import VideoOutputReview
from video.schemas import CostRecord, CostSource, JobStatus, VideoGenerationJob


def make_storyboard() -> PrioritizedStoryboard:
    durations = [2, 2, 2, 3, 3, 3]
    return PrioritizedStoryboard(
        project_id="episode-video-demo",
        episode_number=1,
        target_duration_seconds=15,
        shots=[
            PrioritizedShot(
                shot_id=f"shot-{index}",
                scene_id=f"scene-{index}",
                order=index,
                visual_prompt=f"测试画面 {index}",
                camera_instruction="中景。",
                duration_seconds=duration,
                source_chunk_ids=["chunk-1"],
                importance=ShotImportance.KEY if index == 1 else ShotImportance.STANDARD,
                priority_reason="测试优先级",
                min_quality_score=7 if index == 1 else 5,
            )
            for index, duration in enumerate(durations, start=1)
        ],
    )


def make_completed_job(job_id: str, *, accepted: bool = True) -> VideoGenerationJob:
    return VideoGenerationJob(
        job_id=job_id,
        model_id="mock-balanced",
        status=JobStatus.COMPLETED,
        cost=CostRecord(estimated_usd=0.1, reported_usd=None, source=CostSource.ESTIMATED),
        output_url=f"https://video.example/{job_id}.mp4",
        output_review=VideoOutputReview(
            accepted=accepted,
            visual_quality_score=4,
            prompt_alignment_score=4,
            feedback="人工已检查。",
        ),
    )


def make_links() -> list[ShotVideoTaskLink]:
    return [
        ShotVideoTaskLink(
            project_id="episode-video-demo",
            episode_number=1,
            shot_id=f"shot-{index}",
            video_job_id=f"job-{index}",
            model_id="mock-balanced",
        )
        for index in range(1, 7)
    ]


def test_assembly_preserves_storyboard_order_not_job_input_order(tmp_path):
    jobs = [make_completed_job(f"job-{index}") for index in reversed(range(1, 7))]

    plan = build_episode_assembly_plan(
        make_storyboard(),
        make_links(),
        jobs,
        tmp_path / "episode-1.mp4",
    )

    assert [job.job_id for job in plan.ordered_jobs] == [
        f"job-{index}" for index in range(1, 7)
    ]


def test_assembly_refuses_unreviewed_or_rejected_shots(tmp_path):
    jobs = [make_completed_job(f"job-{index}") for index in range(1, 7)]
    jobs[1].output_review = None
    jobs[4].output_review = VideoOutputReview(
        accepted=False,
        visual_quality_score=2,
        prompt_alignment_score=2,
        feedback="人物不一致。",
    )

    with pytest.raises(EpisodeAssemblyNotReady, match="未人工评审.*人工拒绝"):
        build_episode_assembly_plan(
            make_storyboard(),
            make_links(),
            jobs,
            tmp_path / "episode-1.mp4",
        )
