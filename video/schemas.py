from dataclasses import dataclass
from enum import Enum

from video.output_review import VideoOutputReview


class GenerationMode(str, Enum):
    """用户希望生成视频的输入方式。"""

    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"


class JobStatus(str, Enum):
    """视频生成任务在 Provider 中经历的生命周期。"""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CostSource(str, Enum):
    """某个任务成本数值的证据来源。"""

    ESTIMATED = "estimated"
    PROVIDER_REPORTED = "provider_reported"


@dataclass(frozen=True)
class CostRecord:
    """单个任务的成本记录，明确区分预测值与供应商实报值。"""

    estimated_usd: float
    reported_usd: float | None
    source: CostSource

    def __post_init__(self) -> None:
        if self.estimated_usd < 0:
            raise ValueError("estimated_usd 不能小于 0。")
        if self.reported_usd is not None and self.reported_usd < 0:
            raise ValueError("reported_usd 不能小于 0。")
        if self.source == CostSource.ESTIMATED and self.reported_usd is not None:
            raise ValueError("预估成本记录不能包含 reported_usd。")
        if self.source == CostSource.PROVIDER_REPORTED and self.reported_usd is None:
            raise ValueError("供应商实报成本记录必须包含 reported_usd。")


@dataclass(frozen=True)
class VideoRequest:
    """用户提交给视频生成平台的、与具体模型无关的需求。"""

    prompt: str
    mode: GenerationMode
    duration_seconds: int
    budget_usd: float
    reference_image_url: str | None = None
    min_quality_score: int = 1

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("prompt 不能为空。")
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds 必须大于 0。")
        if self.budget_usd < 0:
            raise ValueError("budget_usd 不能小于 0。")
        if self.mode == GenerationMode.IMAGE_TO_VIDEO and not self.reference_image_url:
            raise ValueError("Image-to-Video 必须提供 reference_image_url。")
        if not 1 <= self.min_quality_score <= 10:
            raise ValueError("min_quality_score 必须在 1 到 10 之间。")


@dataclass(frozen=True)
class VideoModelProfile:
    """Registry 保存的模型能力事实，不包含任何模型选择策略。"""

    model_id: str
    provider: str
    supported_modes: frozenset[GenerationMode]
    cost_per_second: float
    estimated_latency_seconds: int
    quality_score: int
    min_duration_seconds: int
    max_duration_seconds: int


@dataclass
class VideoGenerationJob:
    """一次已提交给 Provider 的具体视频生成任务。"""

    job_id: str
    model_id: str
    status: JobStatus
    # 单任务成本记录。reported_usd 为 None 时，绝不能对外称为实际成本。
    cost: CostRecord
    # Provider 是持久化任务的外部执行者。重启后不能从进程内对象猜测它。
    provider: str = "mock-provider"
    # 保存提交快照，用于审计、失败诊断与后续受控重试；不保存密钥。
    request: VideoRequest | None = None
    output_url: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    retryable: bool | None = None
    output_review: VideoOutputReview | None = None
