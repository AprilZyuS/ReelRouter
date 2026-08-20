"""Runway 的 VideoProvider 适配器。"""

from __future__ import annotations

import httpx

from video.costing import estimate_generation_cost
from video.runway_config import RunwaySettings
from video.schemas import (
    CostRecord,
    CostSource,
    GenerationMode,
    JobStatus,
    VideoGenerationJob,
    VideoModelProfile,
    VideoRequest,
)


_RUNWAY_MODEL_NAMES = {"runway-gen4.5": "gen4.5"}
_RUNWAY_STATUS_MAP = {
    "PENDING": JobStatus.QUEUED,
    "THROTTLED": JobStatus.QUEUED,
    "RUNNING": JobStatus.PROCESSING,
    "SUCCEEDED": JobStatus.COMPLETED,
    "FAILED": JobStatus.FAILED,
    "CANCELED": JobStatus.FAILED,
}


def _failure_details(
    raw_status: str,
    result: dict[str, object],
) -> tuple[str | None, str | None, bool | None]:
    """把 Runway 失败码转为本项目可执行的重试策略。

    True 仅表示“允许在后续策略中延迟重试”，不表示 Provider 会立刻重试。
    None 表示未知失败码，必须交给人工或后续治理策略决定。
    """
    if raw_status == "CANCELED":
        return None, "任务已被取消。", False
    if raw_status != "FAILED":
        return None, None, None

    failure_code = result.get("failureCode")
    failure_code = failure_code if isinstance(failure_code, str) else None
    failure_message = result.get("failure")
    failure_message = failure_message if isinstance(failure_message, str) else None

    # Runway 文档明确说明，这些错误重试不会改变结果，或可能再次触发审核。
    if (
        failure_code is not None
        and (
            failure_code.startswith("SAFETY.")
            or failure_code == "INPUT_PREPROCESSING.SAFETY.TEXT"
            or failure_code == "ASSET.INVALID"
        )
    ):
        return failure_code, failure_message, False

    # 这些通常是临时性问题或系统问题；调用方应退避后再尝试。
    if (
        failure_code is None
        or failure_code.startswith("INTERNAL")
        or failure_code == "INPUT_PREPROCESSING.INTERNAL"
        or failure_code == "THIRD_PARTY.UNAVAILABLE"
    ):
        return failure_code, failure_message, True

    return failure_code, failure_message, None


class RunwayProvider:
    """将 Runway HTTP API 转换为项目统一的 VideoProvider 契约。"""

    def __init__(
        self,
        settings: RunwaySettings,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(
            base_url=settings.base_url.rstrip("/") + "/",
            headers=self._headers(),
            timeout=settings.timeout_seconds,
        )
        self._client.headers.update(self._headers())
        self._jobs: dict[str, VideoGenerationJob] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.api_key}",
            "X-Runway-Version": self._settings.api_version,
            "Accept": "application/json",
        }

    def _model_name(self, model: VideoModelProfile) -> str:
        if model.provider != "runway":
            raise ValueError("RunwayProvider 只能执行 provider 为 runway 的模型。")
        try:
            return _RUNWAY_MODEL_NAMES[model.model_id]
        except KeyError as error:
            raise ValueError(f"未配置 Runway 模型映射：{model.model_id}") from error

    def _request(self, method: str, path: str, **kwargs: object) -> dict[str, object]:
        try:
            response = self._client.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(f"Runway API 请求失败：{error}") from error
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Runway API 返回了非对象 JSON。")
        return payload

    def submit(
        self,
        request: VideoRequest,
        model: VideoModelProfile,
    ) -> VideoGenerationJob:
        """提交任务并返回 queued；真实视频在后续 poll 中获得。"""
        model_name = self._model_name(model)
        estimated_cost = estimate_generation_cost(request, model)
        payload: dict[str, object] = {
            "model": model_name,
            "promptText": request.prompt,
            "duration": request.duration_seconds,
            "ratio": "1280:720",
        }
        if request.mode == GenerationMode.IMAGE_TO_VIDEO:
            payload["promptImage"] = request.reference_image_url
            path = "image_to_video"
        else:
            path = "text_to_video"

        result = self._request("POST", path, json=payload)
        task_id = result.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("Runway API 响应中缺少任务 id。")

        job = VideoGenerationJob(
            job_id=task_id,
            model_id=model.model_id,
            status=JobStatus.QUEUED,
            cost=CostRecord(
                estimated_usd=estimated_cost,
                reported_usd=None,
                source=CostSource.ESTIMATED,
            ),
        )
        self._jobs[job.job_id] = job
        return job

    def poll(self, job_id: str) -> VideoGenerationJob:
        """读取最新状态；不在 Web 请求中 sleep 等待生成完成。"""
        try:
            previous_job = self._jobs[job_id]
        except KeyError as error:
            raise ValueError(f"不存在任务：{job_id}") from error

        result = self._request("GET", f"tasks/{job_id}")
        raw_status = result.get("status")
        if not isinstance(raw_status, str):
            raise RuntimeError("Runway API 响应中缺少状态 status。")
        raw_status = raw_status.upper()
        try:
            status = _RUNWAY_STATUS_MAP[raw_status]
        except KeyError as error:
            raise RuntimeError(f"未知的 Runway 任务状态：{raw_status}") from error

        failure_code, failure_message, retryable = _failure_details(raw_status, result)
        output_url: str | None = None
        if status == JobStatus.COMPLETED:
            output = result.get("output")
            if isinstance(output, list) and output and isinstance(output[0], str):
                output_url = output[0]
            else:
                raise RuntimeError("Runway 已完成任务但未返回视频 output URL。")

        updated_job = VideoGenerationJob(
            job_id=previous_job.job_id,
            model_id=previous_job.model_id,
            status=status,
            cost=previous_job.cost,
            output_url=output_url,
            failure_code=failure_code,
            failure_message=failure_message,
            retryable=retryable,
            output_review=previous_job.output_review,
        )
        self._jobs[job_id] = updated_job
        return updated_job