import pymysql

from video.mysql_config import load_mysql_settings
from video.repository import MySQLVideoJobRepository
from uuid import uuid4

from video.output_review import VideoOutputReview
from video.schemas import (
    CostRecord,
    CostSource,
    JobStatus,
    VideoGenerationJob,
)


def test_setup_creates_video_tables():
    settings = load_mysql_settings()
    repository = MySQLVideoJobRepository(settings)

    repository.setup()

    connection = pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            table_names = {
                row[0]
                for row in cursor.fetchall()
            }

    finally:
        connection.close()

    assert "video_jobs" in table_names
    assert "video_output_reviews" in table_names

def test_save_and_get_completed_job_with_review():
    settings = load_mysql_settings()
    repository = MySQLVideoJobRepository(settings)
    repository.setup()

    job = VideoGenerationJob(
        job_id=f"test-{uuid4()}",
        model_id="mock-balanced",
        status=JobStatus.COMPLETED,
        cost=CostRecord(
            estimated_usd=0.25,
            reported_usd=0.23,
            source=CostSource.PROVIDER_REPORTED,
        ),
        output_url="https://example.com/generated.mp4",
        output_review=VideoOutputReview(
            accepted=True,
            visual_quality_score=4,
            prompt_alignment_score=5,
            feedback="镜头内容与提示词一致。",
        ),
    )

    repository.save(job)
    loaded_job = repository.get(job.job_id)

    assert loaded_job is not None
    assert loaded_job.job_id == job.job_id
    assert loaded_job.status == JobStatus.COMPLETED
    assert loaded_job.cost.estimated_usd == 0.25
    assert loaded_job.cost.reported_usd == 0.23
    assert loaded_job.cost.source == CostSource.PROVIDER_REPORTED
    assert loaded_job.output_url == "https://example.com/generated.mp4"
    assert loaded_job.output_review is not None
    assert loaded_job.output_review.accepted is True
    assert loaded_job.output_review.visual_quality_score == 4

def test_get_returns_none_for_unknown_job():
    settings = load_mysql_settings()
    repository = MySQLVideoJobRepository(settings)
    repository.setup()

    assert repository.get(f"missing-{uuid4()}") is None