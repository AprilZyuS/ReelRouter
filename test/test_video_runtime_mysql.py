from uuid import uuid4

from video.api_router import get_default_video_runtime
from video.repository import MySQLVideoJobRepository
from video.schemas import GenerationMode, VideoRequest


def test_default_video_runtime_persists_job_to_mysql():
    # 避免本测试复用其他测试曾创建的缓存运行时。
    get_default_video_runtime.cache_clear()

    service, _ = get_default_video_runtime()

    assert isinstance(
        service.repository,
        MySQLVideoJobRepository,
    )

    request = VideoRequest(
        prompt="用于验证 MySQL 持久化的一段测试视频。",
        mode=GenerationMode.TEXT_TO_VIDEO,
        duration_seconds=2,
        budget_usd=1.0,
        min_quality_score=1,
    )

    submission = service.create_job(request)

    loaded_job = service.repository.get(
        submission.job.job_id
    )

    assert loaded_job is not None
    assert loaded_job.job_id == submission.job.job_id
    assert loaded_job.status == submission.job.status

    get_default_video_runtime.cache_clear()