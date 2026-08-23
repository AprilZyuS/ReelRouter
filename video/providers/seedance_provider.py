"""火山方舟 Seedance 异步视频生成 Provider。"""

from __future__ import annotations

import httpx

from video.ark_video_config import ArkVideoSettings
from video.costing import estimate_generation_cost
from video.schemas import (
    CostRecord,
    CostSource,
    GenerationMode,
    JobStatus,
    VideoGenerationJob,
    VideoModelProfile,
    VideoRequest,
)


_STATUS_MAP = {
    "queued": JobStatus.QUEUED,
    "running": JobStatus.PROCESSING,
    "succeeded": JobStatus.COMPLETED,
    "failed": JobStatus.FAILED,
    "cancelled": JobStatus.FAILED,
    "expired": JobStatus.FAILED,
}
_NON_RETRYABLE_FAILURES = {
    "InputTextSensitiveContentDetected",
    "InputImageSensitiveContentDetected",
    "OutputVideoSensitiveContentDetected",
}
_RETRYABLE_FAILURES = {"QuotaExceeded", "InternalError", "ServiceUnavailable"}


class SeedanceProvider:
    """将方舟内容生成任务 API 转成项目统一的视频任务契约。"""

    def __init__(
        self,
        settings: ArkVideoSettings,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(
            base_url=settings.base_url.rstrip("/") + "/",
            headers=self._headers(),
            timeout=settings.timeout_seconds,
        )
        self._client.headers.update(self._headers())

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: object) -> dict[str, object]:
        try:
            response = self._client.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            body = error.response.text.strip().replace("\n", " ")[:1_000]
            suffix = f"；Provider 详情：{body}" if body else ""
            raise RuntimeError(f"Seedance API 请求失败：{error}{suffix}") from error
        except httpx.HTTPError as error:
            raise RuntimeError(f"Seedance API 请求失败：{error}") from error
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Seedance API 返回了非对象 JSON。")
        return payload

    @staticmethod
    def _content(request: VideoRequest) -> list[dict[str, object]]:
        content: list[dict[str, object]] = [{"type": "text", "text": request.prompt}]
        if request.mode == GenerationMode.IMAGE_TO_VIDEO:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": request.reference_image_url},
                    "role": "reference_image",
                }
            )
        return content

    @staticmethod
    def _failure(result: dict[str, object]) -> tuple[str | None, str | None, bool | None]:
        error = result.get("error")
        if not isinstance(error, dict):
            return None, None, False if result.get("status") in {"cancelled", "expired"} else None
        code = error.get("code")
        message = error.get("message")
        failure_code = code if isinstance(code, str) else None
        failure_message = message if isinstance(message, str) else None
        if failure_code in _NON_RETRYABLE_FAILURES:
            return failure_code, failure_message, False
        if failure_code in _RETRYABLE_FAILURES:
            return failure_code, failure_message, True
        return failure_code, failure_message, None

    def submit(
        self,
        request: VideoRequest,
        model: VideoModelProfile,
    ) -> VideoGenerationJob:
        if model.provider != "seedance":
            raise ValueError("SeedanceProvider 只能执行 provider 为 seedance 的模型。")
        estimated_cost = estimate_generation_cost(request, model)
        result = self._request(
            "POST",
            "contents/generations/tasks",
            json={
                "model": self._settings.model,
                "content": self._content(request),
                "ratio": "16:9",
                "duration": request.duration_seconds,
                "watermark": False,
            },
        )
        task_id = result.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("Seedance API 响应中缺少任务 id。")
        return VideoGenerationJob(
            job_id=task_id,
            model_id=model.model_id,
            status=JobStatus.QUEUED,
            cost=CostRecord(
                estimated_usd=estimated_cost,
                reported_usd=None,
                source=CostSource.ESTIMATED,
            ),
            provider="seedance",
            request=request,
        )

    def poll(self, previous_job: VideoGenerationJob) -> VideoGenerationJob:
        if previous_job.provider != "seedance":
            raise ValueError("SeedanceProvider 只能轮询 provider 为 seedance 的任务。")
        result = self._request("GET", f"contents/generations/tasks/{previous_job.job_id}")
        raw_status = result.get("status")
        if not isinstance(raw_status, str):
            raise RuntimeError("Seedance API 响应中缺少状态 status。")
        try:
            status = _STATUS_MAP[raw_status.lower()]
        except KeyError as error:
            raise RuntimeError(f"未知的 Seedance 任务状态：{raw_status}") from error

        output_url: str | None = None
        if status == JobStatus.COMPLETED:
            content = result.get("content")
            if isinstance(content, dict):
                candidate = content.get("video_url")
                output_url = candidate if isinstance(candidate, str) and candidate else None
            if output_url is None:
                raise RuntimeError("Seedance 已完成任务但未返回 content.video_url。")
        failure_code, failure_message, retryable = self._failure(result)
        return VideoGenerationJob(
            job_id=previous_job.job_id,
            model_id=previous_job.model_id,
            status=status,
            cost=previous_job.cost,
            provider=previous_job.provider,
            request=previous_job.request,
            output_url=output_url,
            failure_code=failure_code,
            failure_message=failure_message,
            retryable=retryable,
            output_review=previous_job.output_review,
        )
