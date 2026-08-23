from uuid import uuid4

from narrative.video_execution import ShotVideoTaskLink
from narrative.video_task_repository import MySQLShotVideoTaskStore
from narrative.visual_assets import MySQLShotReferenceAssetStore, ShotReferenceAsset
from video.mysql_config import load_mysql_settings
from video.repository import MySQLVideoJobRepository
from video.schemas import CostRecord, CostSource, JobStatus, VideoGenerationJob


def test_mysql_persists_shot_to_video_link_and_reference_asset():
    settings = load_mysql_settings()
    video_repository = MySQLVideoJobRepository(settings)
    video_repository.setup()
    task_store = MySQLShotVideoTaskStore(settings)
    task_store.setup()
    asset_store = MySQLShotReferenceAssetStore(settings)
    asset_store.setup()

    project_id = f"video-project-{uuid4()}"
    job = VideoGenerationJob(
        job_id=f"video-job-{uuid4()}",
        model_id="mock-balanced",
        status=JobStatus.QUEUED,
        cost=CostRecord(estimated_usd=0.1, reported_usd=None, source=CostSource.ESTIMATED),
    )
    video_repository.save(job)
    link = ShotVideoTaskLink(
        project_id=project_id,
        episode_number=1,
        shot_id="shot-001",
        video_job_id=job.job_id,
        model_id=job.model_id,
        reference_asset_id="lin-xiao-v1",
    )
    task_store.save(link)
    asset = ShotReferenceAsset(
        project_id=project_id,
        episode_number=1,
        shot_id="shot-001",
        asset_id="lin-xiao-v1",
        asset_version=1,
        reference_image_url="https://assets.example/lin-xiao-v1.png",
    )
    asset_store.save(asset)

    assert task_store.list_episode(project_id, 1) == [link]
    assert asset_store.list_episode(project_id, 1) == [asset]
