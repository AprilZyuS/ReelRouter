"""高成本视频任务的人类审批记录。

LangGraph 的内存 Checkpoint 适合本地流程演示，但进程重启后不能作为生产
审批凭据。本模块只持久化恢复审批所必需的业务数据：请求快照、已选模型、
成本提示与最终决定；不会保存任何 Provider 密钥。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import pymysql
from pymysql.cursors import DictCursor

from video.mysql_config import MySQLSettings
from video.schemas import GenerationMode, VideoRequest


@dataclass(frozen=True)
class PendingVideoApproval:
    thread_id: str
    request: VideoRequest
    model_id: str
    estimated_cost_usd: float
    selection_reason: str
    budget_reason: str
    status: str = "awaiting"
    feedback: str = ""
    job_id: str | None = None


class VideoApprovalRepository(Protocol):
    def setup(self) -> None: ...

    def save(self, approval: PendingVideoApproval) -> None: ...

    def get(self, thread_id: str) -> PendingVideoApproval | None: ...


class InMemoryVideoApprovalRepository:
    def __init__(self) -> None:
        self._approvals: dict[str, PendingVideoApproval] = {}

    def setup(self) -> None:
        pass

    def save(self, approval: PendingVideoApproval) -> None:
        self._approvals[approval.thread_id] = approval

    def get(self, thread_id: str) -> PendingVideoApproval | None:
        return self._approvals.get(thread_id)


class MySQLVideoApprovalRepository:
    """可重启的视频审批存储；与 video_jobs 使用同一个 MySQL 数据库。"""

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
                    CREATE TABLE IF NOT EXISTS video_pending_approvals (
                        thread_id VARCHAR(64) PRIMARY KEY,
                        request_json JSON NOT NULL,
                        model_id VARCHAR(128) NOT NULL,
                        estimated_cost_usd DECIMAL(10, 4) NOT NULL,
                        selection_reason TEXT NOT NULL,
                        budget_reason TEXT NOT NULL,
                        approval_status VARCHAR(32) NOT NULL,
                        feedback TEXT NOT NULL,
                        job_id VARCHAR(64) NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        CONSTRAINT fk_video_pending_approval_job
                            FOREIGN KEY (job_id) REFERENCES video_jobs(job_id)
                            ON DELETE SET NULL
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

    def save(self, approval: PendingVideoApproval) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO video_pending_approvals (
                        thread_id, request_json, model_id, estimated_cost_usd,
                        selection_reason, budget_reason, approval_status,
                        feedback, job_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        request_json = VALUES(request_json),
                        model_id = VALUES(model_id),
                        estimated_cost_usd = VALUES(estimated_cost_usd),
                        selection_reason = VALUES(selection_reason),
                        budget_reason = VALUES(budget_reason),
                        approval_status = VALUES(approval_status),
                        feedback = VALUES(feedback),
                        job_id = VALUES(job_id)
                    """,
                    (
                        approval.thread_id,
                        self._serialize_request(approval.request),
                        approval.model_id,
                        approval.estimated_cost_usd,
                        approval.selection_reason,
                        approval.budget_reason,
                        approval.status,
                        approval.feedback,
                        approval.job_id,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, thread_id: str) -> PendingVideoApproval | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT thread_id, request_json, model_id, estimated_cost_usd,
                           selection_reason, budget_reason, approval_status,
                           feedback, job_id
                    FROM video_pending_approvals
                    WHERE thread_id = %s
                    """,
                    (thread_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return PendingVideoApproval(
            thread_id=row["thread_id"],
            request=self._deserialize_request(row["request_json"]),
            model_id=row["model_id"],
            estimated_cost_usd=float(row["estimated_cost_usd"]),
            selection_reason=row["selection_reason"],
            budget_reason=row["budget_reason"],
            status=row["approval_status"],
            feedback=row["feedback"],
            job_id=row["job_id"],
        )

    @staticmethod
    def _serialize_request(request: VideoRequest) -> str:
        return json.dumps(
            {
                "prompt": request.prompt,
                "mode": request.mode.value,
                "duration_seconds": request.duration_seconds,
                "budget_usd": request.budget_usd,
                "reference_image_url": request.reference_image_url,
                "min_quality_score": request.min_quality_score,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _deserialize_request(raw: object) -> VideoRequest:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            raise RuntimeError("video_pending_approvals.request_json 无效。")
        return VideoRequest(
            prompt=str(data["prompt"]),
            mode=GenerationMode(str(data["mode"])),
            duration_seconds=int(data["duration_seconds"]),
            budget_usd=float(data["budget_usd"]),
            reference_image_url=data.get("reference_image_url"),
            min_quality_score=int(data["min_quality_score"]),
        )
