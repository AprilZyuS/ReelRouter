"""Runway 连接配置。"""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class RunwaySettings:
    """Runway HTTP 客户端需要的连接参数。"""

    api_key: str
    base_url: str = "https://api.dev.runwayml.com/v1"
    api_version: str = "2024-11-06"
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("RUNWAY_API_KEY 不能为空。")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0。")

    @classmethod
    def from_environment(cls) -> "RunwaySettings":
        """从环境变量创建配置；只在真正启用 Runway 时调用。"""
        api_key = os.getenv("RUNWAY_API_KEY")
        if not api_key:
            raise ValueError("未配置 RUNWAY_API_KEY。")
        return cls(
            api_key=api_key,
            base_url=os.getenv("RUNWAY_BASE_URL", cls.base_url),
            api_version=os.getenv("RUNWAY_API_VERSION", cls.api_version),
        )