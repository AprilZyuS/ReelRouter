"""根据项目创作要求生成结构化小说稿。"""

from __future__ import annotations

import json
from typing import Callable, Protocol

from pydantic import ValidationError

from narrative.schemas import NarrativeProjectRequest, NovelManuscript


class StoryWriterClient(Protocol):
    """对话模型客户端的最小能力约束。"""

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        """接收提示词，返回模型原始文本。"""
        ...


class StoryWriterOutputError(ValueError):
    """模型未返回符合约束的 JSON 小说稿时抛出。"""


class StoryWriter:
    """负责构造提示词、解析模型结果和校验小说稿。"""

    def __init__(
        self,
        client: StoryWriterClient,
        *,
        max_format_retries: int = 1,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        if max_format_retries < 0:
            raise ValueError("max_format_retries 不能小于 0。")
        self.client = client
        self.max_format_retries = max_format_retries
        self.progress_callback = progress_callback

    def generate(self, request: NarrativeProjectRequest) -> NovelManuscript:
        """调用模型并将结果转换为可信的领域对象。

        外部模型不一定一次遵守 JSON 契约。v1 最多执行一次格式修复重试，
        避免无限消耗费用，也避免把不完整原文写入知识库。
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(request)

        for attempt in range(self.max_format_retries + 1):
            raw_response = self.client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            try:
                payload = self._parse_json_object(raw_response)

                # project_id 是系统事实，不相信模型自行生成的值。
                payload["project_id"] = request.project_id
                return NovelManuscript.model_validate(payload)
            except ValidationError as error:
                output_error = StoryWriterOutputError(
                    "模型返回的小说稿不符合 NovelManuscript 数据契约。"
                )
                output_error.__cause__ = error
            except StoryWriterOutputError as error:
                output_error = error

            if attempt == self.max_format_retries:
                raise output_error

            self._report(
                "Story Writer 输出未通过 JSON/数据契约校验，"
                f"正在进行第 {attempt + 1} 次格式修复重试。"
            )
            user_prompt = self._build_retry_user_prompt(request, output_error)

    @staticmethod
    def _build_system_prompt() -> str:
        return """你是中文长篇小说创作 Agent。
根据用户提供的创作要求，生成适合后续改编为多集短视频的原创小说稿。

你必须只返回一个合法 JSON 对象，不能使用 Markdown 代码块，不能添加解释文字。
JSON 必须且只能包含以下字段：
- title: 小说标题
- logline: 一句话故事梗概
- manuscript: 完整小说正文，必须为 800 到 900 个中文字符
- style_bible: 持续适用的叙事和视觉风格设定
- planned_episode_count: 建议拆分的集数，范围 2 到 20

小说必须有明确的人物目标、冲突、转折、悬念，并为后续分集改编留下空间。
JSON 字符串中的双引号、换行必须使用合法 JSON 转义；生成结束前必须闭合所有引号、方括号和花括号。"""

    @staticmethod
    def _build_user_prompt(request: NarrativeProjectRequest) -> str:
        requirements = {
            "标题偏好": request.title,
            "关键词": request.keywords,
            "题材": request.genre,
            "视觉风格": request.visual_style,
            "每集目标时长（秒）": request.episode_duration_seconds,
            "单集预算（美元）": request.episode_budget_usd,
        }
        return (
            "请依据以下创作要求生成小说稿：\n"
            + json.dumps(requirements, ensure_ascii=False, indent=2)
        )

    @staticmethod
    def _build_retry_user_prompt(
        request: NarrativeProjectRequest,
        error: StoryWriterOutputError,
    ) -> str:
        """要求模型完全重写短版本 JSON，不尝试在截断文本后继续补写。"""
        return (
            StoryWriter._build_user_prompt(request)
            + "\n\n上一版输出未通过结构化校验："
            + str(error)
            + "\n请完整重写，不要续写上一版。"
            + "只返回一个可被 json.loads 解析的 JSON 对象，不能使用 Markdown。"
            + "请将 manuscript 严格控制在 800 到 850 个中文字符，并完成所有 JSON 闭合符号。"
        )

    @staticmethod
    def _parse_json_object(raw_response: str) -> dict[str, object]:
        """严格解析模型返回的 JSON 对象。"""
        try:
            payload = json.loads(raw_response.strip())
        except json.JSONDecodeError as error:
            raise StoryWriterOutputError(
                "模型返回的内容不是合法 JSON；"
                f"响应字符数：{len(raw_response.strip())}，解析原因：{error.msg}。"
            ) from error

        if not isinstance(payload, dict):
            raise StoryWriterOutputError("模型返回的 JSON 顶层必须是对象。")

        return payload

    def _report(self, message: str) -> None:
        """把重试状态交给 CLI/API 观察层，避免核心逻辑耦合 print。"""
        if self.progress_callback is not None:
            self.progress_callback(message)
