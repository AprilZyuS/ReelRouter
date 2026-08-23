"""火山方舟 OpenAI 兼容接口的通用 Story Writer 客户端。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Protocol

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI


DEFAULT_STORY_MAX_TOKENS = 8_192
DEFAULT_STORY_THINKING = "disabled"
DEFAULT_STORY_TEMPERATURE = 0.2

# Story Writer 也可以被脚本单独导入，因此不能依赖 video.mysql_config 的导入副作用
# 才能读取 .env。系统环境变量仍优先于 .env 中的同名配置。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


class ChatModel(Protocol):
    """真实 ChatOpenAI 与测试替身共同满足的最小接口。"""

    def invoke(self, messages: list[BaseMessage]) -> object:
        """发送消息并返回模型响应。"""
        ...


class ArkConfigurationError(RuntimeError):
    """方舟 Story Writer 配置缺失或无效时抛出。"""


class ArkResponseError(RuntimeError):
    """方舟模型没有返回可用文本时抛出。"""


class ArkStoryWriterClient:
    """将任意方舟 Chat 模型适配为 StoryWriterClient 所需的 generate 接口。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        thinking: str | None = None,
        temperature: float | None = None,
        llm: ChatModel | None = None,
        llm_factory: Callable[..., ChatModel] = ChatOpenAI,
    ) -> None:
        # 注入 llm 仅用于测试，因此测试不需要真实 API Key 或环境变量。
        if llm is not None:
            self.model = model or "injected-test-model"
            self.max_tokens = self._normalize_max_tokens(
                max_tokens if max_tokens is not None else DEFAULT_STORY_MAX_TOKENS
            )
            self.thinking = self._normalize_thinking(
                thinking if thinking is not None else DEFAULT_STORY_THINKING
            )
            self.temperature = self._normalize_temperature(
                temperature
                if temperature is not None
                else DEFAULT_STORY_TEMPERATURE
            )
            self.llm = llm
            return

        self.model = self._required_value("ARK_STORY_MODEL", model)
        self.max_tokens = self._load_max_tokens(max_tokens)
        self.thinking = self._load_thinking(thinking)
        self.temperature = self._load_temperature(temperature)
        self.llm = llm_factory(
            model=self.model,
            api_key=self._required_value("ARK_API_KEY", api_key),
            base_url=self._required_value("ARK_BASE_URL", base_url),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            max_retries=1,
            # 对结构化创作任务默认关闭深度思考，避免 reasoning 耗尽输出额度后
            # 只收到 finish_reason=length 而没有 JSON 正文。
            extra_body={"thinking": {"type": self.thinking}},
        )

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        """调用方舟模型并只返回助手的最终文本内容。"""
        response = self.llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )

        content = self._extract_text_content(response)
        if content is None:
            raise ArkResponseError(self._build_empty_response_message(response))

        return content

    @staticmethod
    def _extract_text_content(response: object) -> str | None:
        """兼容 LangChain 的字符串 content 与 OpenAI 风格内容块列表。"""
        content = getattr(response, "content", None)
        if isinstance(content, str):
            normalized = content.strip()
            return normalized or None

        if not isinstance(content, list):
            return None

        text_parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
                continue
            if not isinstance(block, dict):
                continue

            text = block.get("text")
            if isinstance(text, str):
                text_parts.append(text)

        normalized = "".join(text_parts).strip()
        return normalized or None

    @staticmethod
    def _build_empty_response_message(response: object) -> str:
        """保留足够诊断信息，但不输出提示词、密钥或完整模型响应。"""
        content = getattr(response, "content", None)
        content_type = type(content).__name__
        additional_kwargs = getattr(response, "additional_kwargs", {})
        response_metadata = getattr(response, "response_metadata", {})
        metadata = response_metadata if isinstance(response_metadata, dict) else {}
        diagnostics = ArkStoryWriterClient._safe_response_diagnostics(
            metadata,
            additional_kwargs,
            getattr(response, "usage_metadata", {}),
        )
        if (
            isinstance(additional_kwargs, dict)
            and isinstance(additional_kwargs.get("reasoning_content"), str)
            and additional_kwargs["reasoning_content"].strip()
        ):
            message = (
                "方舟模型未返回最终文本，仅返回了 reasoning_content；"
                "请检查该模型的思考模式与 max_tokens 配置。"
            )
        else:
            message = f"方舟模型未返回非空文本响应（content 类型：{content_type}）。"

        if diagnostics:
            return f"{message} 安全诊断：{'；'.join(diagnostics)}。"
        return message

    @staticmethod
    def _safe_response_diagnostics(
        response_metadata: dict[object, object],
        additional_kwargs: object,
        usage_metadata: object = None,
    ) -> list[str]:
        """提取诊断所需的非敏感字段，不记录原始模型文本或调用密钥。"""
        diagnostics: list[str] = []
        finish_reason = response_metadata.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason:
            diagnostics.append(f"finish_reason={finish_reason}")

        model_name = response_metadata.get("model_name") or response_metadata.get(
            "model"
        )
        if isinstance(model_name, str) and model_name:
            diagnostics.append(f"model={model_name}")

        if isinstance(additional_kwargs, dict) and additional_kwargs.get("refusal"):
            diagnostics.append("refusal_detected=true")

        if isinstance(usage_metadata, dict):
            for source_name, display_name in (
                ("input_tokens", "input_tokens"),
                ("output_tokens", "output_tokens"),
                ("total_tokens", "total_tokens"),
                ("reasoning_tokens", "reasoning_tokens"),
            ):
                value = usage_metadata.get(source_name)
                if isinstance(value, int) and value >= 0:
                    diagnostics.append(f"{display_name}={value}")

        return diagnostics

    @staticmethod
    def _required_value(
        environment_name: str,
        explicit_value: str | None = None,
    ) -> str:
        """优先使用显式传参；生产环境则读取 Windows 环境变量。"""
        value = explicit_value or os.getenv(environment_name)
        if not value or not value.strip():
            raise ArkConfigurationError(f"缺少环境变量 {environment_name}。")
        return value

    @classmethod
    def _load_max_tokens(cls, explicit_value: int | None) -> int:
        """读取可选的输出上限；未配置时使用适合推理模型的保守默认值。"""
        if explicit_value is not None:
            return cls._normalize_max_tokens(explicit_value)

        raw_value = os.getenv("ARK_STORY_MAX_TOKENS")
        if raw_value is None or not raw_value.strip():
            return DEFAULT_STORY_MAX_TOKENS
        try:
            return cls._normalize_max_tokens(int(raw_value))
        except ValueError as error:
            raise ArkConfigurationError(
                "ARK_STORY_MAX_TOKENS 必须是大于 0 的整数。"
            ) from error

    @classmethod
    def _load_thinking(cls, explicit_value: str | None) -> str:
        """读取思考模式；结构化 JSON 任务默认关闭以优先保证最终正文。"""
        value = explicit_value or os.getenv("ARK_STORY_THINKING", DEFAULT_STORY_THINKING)
        return cls._normalize_thinking(value)

    @classmethod
    def _load_temperature(cls, explicit_value: float | None) -> float:
        """读取采样温度；默认偏低以提高 JSON 格式稳定性。"""
        if explicit_value is not None:
            return cls._normalize_temperature(explicit_value)

        raw_value = os.getenv("ARK_STORY_TEMPERATURE")
        if raw_value is None or not raw_value.strip():
            return DEFAULT_STORY_TEMPERATURE
        try:
            return cls._normalize_temperature(float(raw_value))
        except ValueError as error:
            raise ArkConfigurationError(
                "ARK_STORY_TEMPERATURE 必须是 0 到 2 之间的数字。"
            ) from error

    @staticmethod
    def _normalize_max_tokens(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("max_tokens 必须是大于 0 的整数。")
        return value

    @staticmethod
    def _normalize_thinking(value: str) -> str:
        normalized = value.strip().lower() if isinstance(value, str) else ""
        if normalized not in {"enabled", "disabled"}:
            raise ArkConfigurationError(
                "ARK_STORY_THINKING 只能是 enabled 或 disabled。"
            )
        return normalized

    @staticmethod
    def _normalize_temperature(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("temperature 必须是 0 到 2 之间的数字。")
        normalized = float(value)
        if not 0 <= normalized <= 2:
            raise ValueError("temperature 必须是 0 到 2 之间的数字。")
        return normalized
