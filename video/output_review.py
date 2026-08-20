"""完成视频的人类质量评审领域模型。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoOutputReview:
    """人看过真实视频后留下的质量结论，而非模型臆测的评分。"""

    accepted: bool
    visual_quality_score: int
    prompt_alignment_score: int
    feedback: str

    def __post_init__(self) -> None:
        if not 1 <= self.visual_quality_score <= 5:
            raise ValueError("visual_quality_score 必须在 1 到 5 之间。")
        if not 1 <= self.prompt_alignment_score <= 5:
            raise ValueError("prompt_alignment_score 必须在 1 到 5 之间。")
        if not self.accepted and not self.feedback.strip():
            raise ValueError("拒绝视频时必须提供 feedback。")