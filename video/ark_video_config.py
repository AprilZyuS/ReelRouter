"""火山方舟 Seedance 视频接口的连接与成本预估配置。"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ArkVideoSettings:
    """运行 Seedance Provider 所需的配置。

    方舟视频按 token 等维度计费，不能伪装成固定的真实美元单价。
    ``estimated_cost_per_second_usd`` 只是项目预算护栏使用的保守预估值；
    首次单镜头试运行后，应根据控制台账单和实际用量校准它。
    """

    api_key: str
    model: str
    estimated_cost_per_second_usd: float
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("ARK_API_KEY 不能为空。")
        if not self.model.strip():
            raise ValueError("DOUBAO_VIDEO_MODEL 不能为空。")
        if self.estimated_cost_per_second_usd <= 0:
            raise ValueError("SEEDANCE_ESTIMATED_COST_PER_SECOND_USD 必须大于 0。")
        if self.timeout_seconds <= 0:
            raise ValueError("ARK_VIDEO_TIMEOUT_SECONDS 必须大于 0。")

    @classmethod
    def from_environment(cls) -> "ArkVideoSettings":
        """只在用户明确选择 seedance Provider 时读取视频模型配置。"""
        api_key = os.getenv("ARK_API_KEY")
        model = os.getenv("DOUBAO_VIDEO_MODEL")
        estimate = os.getenv("SEEDANCE_ESTIMATED_COST_PER_SECOND_USD")
        if not api_key:
            raise ValueError("未配置 ARK_API_KEY。")
        if not model:
            raise ValueError("未配置 DOUBAO_VIDEO_MODEL。")
        if not estimate:
            raise ValueError(
                "未配置 SEEDANCE_ESTIMATED_COST_PER_SECOND_USD。"
                "它是预算预检的保守预估值，不是供应商实时报价。"
            )
        try:
            estimated_cost_per_second_usd = float(estimate)
        except ValueError as error:
            raise ValueError(
                "SEEDANCE_ESTIMATED_COST_PER_SECOND_USD 必须是数字。"
            ) from error
        timeout_text = os.getenv("ARK_VIDEO_TIMEOUT_SECONDS", "60")
        try:
            timeout_seconds = float(timeout_text)
        except ValueError as error:
            raise ValueError("ARK_VIDEO_TIMEOUT_SECONDS 必须是数字。") from error
        return cls(
            api_key=api_key,
            model=model,
            estimated_cost_per_second_usd=estimated_cost_per_second_usd,
            base_url=os.getenv("ARK_BASE_URL", cls.base_url),
            timeout_seconds=timeout_seconds,
        )
