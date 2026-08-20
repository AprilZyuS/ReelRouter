from typing import Protocol

from video.output_review import VideoOutputReview
from video.schemas import (
    CostRecord,
    CostSource,
    JobStatus,
    VideoGenerationJob,
)
import pymysql
from pymysql.cursors import DictCursor

from video.mysql_config import MySQLSettings


class VideoJobRepository(Protocol):
    """视频任务的存取契约。Service 只依赖它，不关心数据存在哪里。"""

    def save(self, job: VideoGenerationJob) -> None:
        """新增或覆盖保存任务。"""
        ...

    def get(self, job_id: str) -> VideoGenerationJob | None:
        """按任务 ID 查询；不存在时返回 None。"""
        ...


class InMemoryVideoJobRepository:
    """
    仅用于当前测试和本地开发。

    下一步会新增 MySQLVideoJobRepository，二者都遵守同一个接口。
    """

    def __init__(self) -> None:
        self._jobs: dict[str, VideoGenerationJob] = {}

    def save(self, job: VideoGenerationJob) -> None:
        self._jobs[job.job_id] = job

    def get(self, job_id: str) -> VideoGenerationJob | None:
        return self._jobs.get(job_id)


class MySQLVideoJobRepository:
    """使用 MySQL 保存视频任务与人工输出评审。"""

    def __init__(self, settings: MySQLSettings) -> None:
        self.settings = settings

    def _connect(self):
        """创建一次 MySQL 连接；每次业务操作后都会关闭。"""
        return pymysql.connect(
            host=self.settings.host,
            port=self.settings.port,
            user=self.settings.user,
            password=self.settings.password,
            database=self.settings.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )

    def setup(self) -> None:
        """首次运行时创建业务表；重复调用也安全。"""
        connection = self._connect()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS video_jobs (
                        job_id VARCHAR(64) PRIMARY KEY,
                        model_id VARCHAR(128) NOT NULL,
                        status VARCHAR(32) NOT NULL,

                        estimated_cost_usd DECIMAL(10, 4) NOT NULL,
                        reported_cost_usd DECIMAL(10, 4) NULL,
                        cost_source VARCHAR(32) NOT NULL,

                        output_url TEXT NULL,
                        failure_code VARCHAR(128) NULL,
                        failure_message TEXT NULL,
                        retryable BOOLEAN NULL,

                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )

                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS video_output_reviews (
                        job_id VARCHAR(64) PRIMARY KEY,

                        accepted BOOLEAN NOT NULL,
                        visual_quality_score TINYINT NOT NULL,
                        prompt_alignment_score TINYINT NOT NULL,
                        feedback TEXT NOT NULL,

                        reviewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

                        CONSTRAINT fk_video_output_reviews_job
                            FOREIGN KEY (job_id)
                            REFERENCES video_jobs(job_id)
                            ON DELETE CASCADE
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def save(self, job: VideoGenerationJob) -> None:
        """新增或更新视频任务；有人工评审时一并保存。"""
        connection = self._connect()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO video_jobs (
                        job_id,
                        model_id,
                        status,
                        estimated_cost_usd,
                        reported_cost_usd,
                        cost_source,
                        output_url,
                        failure_code,
                        failure_message,
                        retryable
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        model_id = VALUES(model_id),
                        status = VALUES(status),
                        estimated_cost_usd = VALUES(estimated_cost_usd),
                        reported_cost_usd = VALUES(reported_cost_usd),
                        cost_source = VALUES(cost_source),
                        output_url = VALUES(output_url),
                        failure_code = VALUES(failure_code),
                        failure_message = VALUES(failure_message),
                        retryable = VALUES(retryable)
                    """,
                    (
                        job.job_id,
                        job.model_id,
                        job.status.value,
                        job.cost.estimated_usd,
                        job.cost.reported_usd,
                        job.cost.source.value,
                        job.output_url,
                        job.failure_code,
                        job.failure_message,
                        job.retryable,
                    ),
                )

                if job.output_review is not None:
                    review = job.output_review

                    cursor.execute(
                        """
                        INSERT INTO video_output_reviews (
                            job_id,
                            accepted,
                            visual_quality_score,
                            prompt_alignment_score,
                            feedback
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            accepted = VALUES(accepted),
                            visual_quality_score = VALUES(visual_quality_score),
                            prompt_alignment_score =
                                VALUES(prompt_alignment_score),
                            feedback = VALUES(feedback),
                            reviewed_at = CURRENT_TIMESTAMP
                        """,
                        (
                            job.job_id,
                            review.accepted,
                            review.visual_quality_score,
                            review.prompt_alignment_score,
                            review.feedback,
                        ),
                    )

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def get(self, job_id: str) -> VideoGenerationJob | None:
        """从两张表还原一个完整的视频任务对象。"""
        connection = self._connect()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        j.job_id,
                        j.model_id,
                        j.status,
                        j.estimated_cost_usd,
                        j.reported_cost_usd,
                        j.cost_source,
                        j.output_url,
                        j.failure_code,
                        j.failure_message,
                        j.retryable,

                        r.job_id AS review_job_id,
                        r.accepted AS review_accepted,
                        r.visual_quality_score,
                        r.prompt_alignment_score,
                        r.feedback AS review_feedback

                    FROM video_jobs AS j
                    LEFT JOIN video_output_reviews AS r
                        ON j.job_id = r.job_id
                    WHERE j.job_id = %s
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()

        finally:
            connection.close()

        if row is None:
            return None

        output_review = None
        if row["review_job_id"] is not None:
            output_review = VideoOutputReview(
                accepted=bool(row["review_accepted"]),
                visual_quality_score=int(row["visual_quality_score"]),
                prompt_alignment_score=int(
                    row["prompt_alignment_score"]
                ),
                feedback=row["review_feedback"],
            )

        reported_cost = row["reported_cost_usd"]
        cost = CostRecord(
            estimated_usd=float(row["estimated_cost_usd"]),
            reported_usd=(
                float(reported_cost)
                if reported_cost is not None
                else None
            ),
            source=CostSource(row["cost_source"]),
        )

        retryable = row["retryable"]
        return VideoGenerationJob(
            job_id=row["job_id"],
            model_id=row["model_id"],
            status=JobStatus(row["status"]),
            cost=cost,
            output_url=row["output_url"],
            failure_code=row["failure_code"],
            failure_message=row["failure_message"],
            retryable=(
                bool(retryable)
                if retryable is not None
                else None
            ),
            output_review=output_review,
        )