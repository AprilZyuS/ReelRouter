"""视频 HTTP API 使用的请求与响应模型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from video.model_router import ModelSelection
from video.output_review import VideoOutputReview
from video.schemas import (
    CostRecord,
    CostSource,
    GenerationMode,
    JobStatus,
    VideoGenerationJob,
    VideoRequest,
)


class VideoJobCreateRequest(BaseModel):
    """客户端创建视频任务时发送的 JSON 数据。"""

    prompt: str = Field(min_length=1, max_length=1000)
    mode: GenerationMode
    duration_seconds: int = Field(gt=0)
    budget_usd: float = Field(ge=0)
    min_quality_score: int = Field(default=1, ge=1, le=10)
    reference_image_url: str | None = None

    def to_domain(self) -> VideoRequest:
        return VideoRequest(
            prompt=self.prompt,
            mode=self.mode,
            duration_seconds=self.duration_seconds,
            budget_usd=self.budget_usd,
            min_quality_score=self.min_quality_score,
            reference_image_url=self.reference_image_url,
        )


class CostRecordResponse(BaseModel):
    """对外返回任务成本及其可靠性来源。"""

    estimated_usd: float
    reported_usd: float | None
    source: CostSource

    @classmethod
    def from_domain(cls, cost: CostRecord) -> "CostRecordResponse":
        return cls(
            estimated_usd=cost.estimated_usd,
            reported_usd=cost.reported_usd,
            source=cost.source,
        )


class VideoOutputReviewRequest(BaseModel):
    """用户看完视频后提交的质量评审。"""

    accepted: bool
    visual_quality_score: int = Field(ge=1, le=5)
    prompt_alignment_score: int = Field(ge=1, le=5)
    feedback: str = Field(default="", max_length=1000)

    def to_domain(self) -> VideoOutputReview:
        return VideoOutputReview(
            accepted=self.accepted,
            visual_quality_score=self.visual_quality_score,
            prompt_alignment_score=self.prompt_alignment_score,
            feedback=self.feedback,
        )


class VideoOutputReviewResponse(BaseModel):
    """已保存的人类质量评审。"""

    accepted: bool
    visual_quality_score: int
    prompt_alignment_score: int
    feedback: str

    @classmethod
    def from_domain(cls, review: VideoOutputReview) -> "VideoOutputReviewResponse":
        return cls(
            accepted=review.accepted,
            visual_quality_score=review.visual_quality_score,
            prompt_alignment_score=review.prompt_alignment_score,
            feedback=review.feedback,
        )


class VideoJobStatusResponse(BaseModel):
    """查询任务状态时返回的稳定数据格式。"""

    model_config = ConfigDict(protected_namespaces=())

    job_id: str
    model_id: str
    status: JobStatus
    cost: CostRecordResponse
    output_url: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    retryable: bool | None = None
    output_review: VideoOutputReviewResponse | None = None

    @classmethod
    def from_job(cls, job: VideoGenerationJob) -> "VideoJobStatusResponse":
        return cls(
            job_id=job.job_id,
            model_id=job.model_id,
            status=job.status,
            cost=CostRecordResponse.from_domain(job.cost),
            output_url=job.output_url,
            failure_code=job.failure_code,
            failure_message=job.failure_message,
            retryable=job.retryable,
            output_review=(
                VideoOutputReviewResponse.from_domain(job.output_review)
                if job.output_review is not None
                else None
            ),
        )


class VideoJobCreatedResponse(VideoJobStatusResponse):
    """创建任务后额外返回模型选择理由。"""

    selection_reason: str


class VideoApprovalRequest(BaseModel):
    """用户恢复高成本任务时提交的审批决定。"""

    action: Literal["approve", "reject"]
    feedback: str = Field(default="", max_length=1000)


class ModelSelectionResponse(BaseModel):
    """对外暴露的模型选择信息，不直接泄露内部 dataclass。"""

    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    estimated_cost_usd: float
    reason: str

    @classmethod
    def from_selection(cls, selection: ModelSelection) -> "ModelSelectionResponse":
        return cls(
            model_id=selection.model.model_id,
            estimated_cost_usd=selection.estimated_cost_usd,
            reason=selection.reason,
        )


class VideoWorkflowResponse(BaseModel):
    """创建或恢复视频工作流后返回的统一状态。"""

    thread_id: str
    status: Literal[
        "submitted",
        "awaiting_human_review",
        "rejected",
        "failed",
    ]
    selection: ModelSelectionResponse | None = None
    job: VideoJobStatusResponse | None = None
    approval_status: Literal["approved", "rejected"] | None = None
    error: str | None = None
    interrupt: dict | None = None