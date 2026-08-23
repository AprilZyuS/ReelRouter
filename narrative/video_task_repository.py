"""持久化叙事镜头与视频 Provider 任务之间的映射。"""

from __future__ import annotations

import pymysql
from pymysql.cursors import DictCursor

from narrative.video_execution import ShotVideoTaskLink
from video.mysql_config import MySQLSettings


class MySQLShotVideoTaskStore:
    def __init__(self, settings: MySQLSettings) -> None:
        self.settings = settings

    def _connect(self):
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
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_shot_video_jobs (
                        project_id VARCHAR(64) NOT NULL,
                        episode_number INT UNSIGNED NOT NULL,
                        shot_id VARCHAR(64) NOT NULL,
                        video_job_id VARCHAR(64) NOT NULL,
                        model_id VARCHAR(128) NOT NULL,
                        reference_asset_id VARCHAR(128) NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (project_id, episode_number, shot_id),
                        UNIQUE KEY uq_narrative_shot_video_job (video_job_id),
                        CONSTRAINT fk_narrative_shot_video_job
                            FOREIGN KEY (video_job_id)
                            REFERENCES video_jobs(job_id)
                            ON DELETE CASCADE
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = 'narrative_shot_video_jobs'
                      AND column_name = 'reference_asset_id'
                    """,
                    (self.settings.database,),
                )
                if cursor.fetchone() is None:
                    cursor.execute(
                        """
                        ALTER TABLE narrative_shot_video_jobs
                        ADD COLUMN reference_asset_id VARCHAR(128) NULL
                        """
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save(self, link: ShotVideoTaskLink) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO narrative_shot_video_jobs (
                        project_id, episode_number, shot_id, video_job_id, model_id,
                        reference_asset_id
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        video_job_id = VALUES(video_job_id),
                        model_id = VALUES(model_id),
                        reference_asset_id = VALUES(reference_asset_id)
                    """,
                    (
                        link.project_id,
                        link.episode_number,
                        link.shot_id,
                        link.video_job_id,
                        link.model_id,
                        link.reference_asset_id,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_episode(
        self,
        project_id: str,
        episode_number: int,
    ) -> list[ShotVideoTaskLink]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT project_id, episode_number, shot_id, video_job_id, model_id,
                           reference_asset_id
                    FROM narrative_shot_video_jobs
                    WHERE project_id = %s AND episode_number = %s
                    ORDER BY shot_id ASC
                    """,
                    (project_id, episode_number),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [ShotVideoTaskLink(**row) for row in rows]
