"""将受控 Context Pack 转换为带原文证据的结构化单集剧本。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol

from pydantic import ValidationError

from narrative.schemas import ContextPack, Screenplay


MAX_SPOKEN_CHARACTERS_PER_SECOND = 7
# 给模型的目标比硬校验略保守，为标点、停顿和情绪表演留出余量。
TARGET_SPOKEN_CHARACTERS_PER_SECOND = 6


class ScreenwriterClient(Protocol):
    """Screenwriter 所需的最小模型能力。"""

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        """接收提示词并返回模型原始文本。"""
        ...


class ScreenwriterOutputError(ValueError):
    """模型剧本没有通过 JSON、数据契约或原文证据校验时抛出。"""


class Screenwriter:
    """负责剧本提示词、结构化解析和确定性校验。

    LLM 只能输出 scenes。剧本所属项目、集号、目标时长均由 Context Pack
    注入，避免模型改写系统事实或绕过视频预算前提。
    """

    def __init__(
        self,
        client: ScreenwriterClient,
        *,
        max_format_retries: int = 1,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        if max_format_retries < 0:
            raise ValueError("max_format_retries 不能小于 0。")
        self.client = client
        self.max_format_retries = max_format_retries
        self.progress_callback = progress_callback

    def write(self, context: ContextPack) -> Screenplay:
        """基于一集受控上下文生成 3 至 6 个场景的剧本。"""
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(context)

        for attempt in range(self.max_format_retries + 1):
            raw_response = self.client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            try:
                payload = self._parse_json_object(raw_response)
                screenplay = Screenplay.model_validate(
                    {
                        "project_id": context.episode.project_id,
                        "episode_number": context.episode.episode_number,
                        "target_duration_seconds": (
                            context.episode.target_duration_seconds
                        ),
                        "scenes": payload.get("scenes"),
                    }
                )
                self._validate_business_rules(screenplay, context)
                return screenplay
            except ValidationError as error:
                output_error = ScreenwriterOutputError(
                    "模型返回的剧本不符合 Screenplay 数据契约。"
                )
                output_error.__cause__ = error
            except ScreenwriterOutputError as error:
                output_error = error

            if attempt == self.max_format_retries:
                raise output_error

            self._report(
                "Screenwriter 输出未通过 JSON/业务校验，"
                f"正在进行第 {attempt + 1} 次格式修复重试。"
            )
            user_prompt = self._build_retry_user_prompt(user_prompt, output_error)

        raise AssertionError("不可达：循环会在成功返回或最后一次失败时结束。")

    @staticmethod
    def _build_system_prompt() -> str:
        return """你是 ReelRouter 的中文短剧编剧 Agent。
你只能依据 Context Pack 中的原文证据、角色、长期事实和上一集总结编写本集，
不得补写未提供的关键人物、事件、结局或角色外貌。

只返回一个合法 JSON 对象，不能使用 Markdown 代码块或解释文字。
JSON 必须且只能包含 scenes。scenes 必须是 3 到 6 个场景组成的数组；每个元素
必须且只能包含：scene_id、order、narration、dialogue、visual_description、
duration_seconds、source_chunk_ids。

规则：
1. order 必须从 1 连续递增，scene_id 必须唯一。
2. 所有 duration_seconds 的和必须严格等于 Context Pack 中的目标时长；单个场景为 2 到 15 秒。
3. 每个场景都必须引用至少一个 Context Pack 中提供的 source_chunk_ids，不能编造 ID。
4. narration 与 dialogue 的非空白字符总数需要一起计算，不要在 narration 中重复 dialogue。
   先为场景分配 duration_seconds，再控制口播：建议目标为“场景秒数 × 6”字，
   硬上限为“场景秒数 × 7”字。例如 6 秒镜头建议不超过 36 字，绝不能超过 42 字；
   8 秒镜头建议不超过 48 字，绝不能超过 56 字。短镜头有对白时，应优先减少旁白。
   visual_description 不计入上述口播字数，但必须可拍摄。
5. 如果 episode.scope 存在：只可推进 must_include，不能展开或解决 must_defer；
   最后一个场景必须自然落在 scope.ending_beat 与 closing_hook，而不是提前解决悬念。
6. 每个场景的 source_chunk_ids 只能引用 episode.source_chunk_ids。Context Pack 中其余
   RAG 补充块只能帮助理解，不能作为本集新增剧情的出处。
7. JSON 字符串中的引号与换行必须合法转义，并闭合所有 JSON 符号。"""

    @staticmethod
    def _build_user_prompt(context: ContextPack) -> str:
        """只将当前单集的受控上下文传给模型，保留每段原文的稳定 ID。"""
        context_data = {
            "episode": context.episode.model_dump(),
            "source_chunks": [chunk.model_dump() for chunk in context.source_chunks],
            "characters": [character.model_dump() for character in context.characters],
            "canonical_facts": context.canonical_facts,
            "previous_episode_summary": (
                context.previous_episode_summary.model_dump()
                if context.previous_episode_summary is not None
                else None
            ),
            "style_bible": context.style_bible,
        }
        return "请基于以下 Context Pack 编写本集剧本：\n" + json.dumps(
            context_data,
            ensure_ascii=False,
            indent=2,
        )

    @staticmethod
    def _build_retry_user_prompt(
        original_prompt: str,
        error: ScreenwriterOutputError,
    ) -> str:
        return (
            original_prompt
            + "\n\n上一版输出未通过校验："
            + str(error)
            + "\n请完整重写，并逐项修复以上问题。"
            + "\n若提示口播预算超标，必须将对应场景的 narration + dialogue "
            "压缩到报错中“重写目标”以内；这是为了给配音停顿预留余量。"
            + "\n不得改变 target_duration_seconds、场景数量、scene_id、"
            "scene 顺序、source_chunk_ids 或最后的 closing_hook。"
            + "\n只返回可被 json.loads 解析的 JSON 对象，不能解释。"
        )

    @staticmethod
    def _parse_json_object(raw_response: str) -> dict[str, object]:
        try:
            payload = json.loads(raw_response.strip())
        except json.JSONDecodeError as error:
            raise ScreenwriterOutputError(
                "模型返回的内容不是合法 JSON；"
                f"响应字符数：{len(raw_response.strip())}，解析原因：{error.msg}。"
            ) from error
        if not isinstance(payload, dict):
            raise ScreenwriterOutputError("模型返回的 JSON 顶层必须是对象。")
        return payload

    @staticmethod
    def _validate_business_rules(
        screenplay: Screenplay,
        context: ContextPack,
    ) -> None:
        if not 3 <= len(screenplay.scenes) <= 6:
            raise ScreenwriterOutputError("Screenwriter 必须返回 3 到 6 个场景。")

        allowed_chunk_ids = set(context.episode.source_chunk_ids)
        unknown_evidence = sorted(
            {
                chunk_id
                for scene in screenplay.scenes
                for chunk_id in scene.source_chunk_ids
                if chunk_id not in allowed_chunk_ids
            }
        )
        if unknown_evidence:
            raise ScreenwriterOutputError(
                "剧本场景引用了本集 EpisodePlan 范围外的 source_chunk_ids："
                + ", ".join(unknown_evidence)
            )

        overlong_scenes = [
            (
                scene.scene_id,
                Screenwriter._spoken_character_count(scene.narration, scene.dialogue),
                scene.duration_seconds * MAX_SPOKEN_CHARACTERS_PER_SECOND,
                scene.duration_seconds * TARGET_SPOKEN_CHARACTERS_PER_SECOND,
            )
            for scene in screenplay.scenes
            if Screenwriter._spoken_character_count(scene.narration, scene.dialogue)
            > scene.duration_seconds * MAX_SPOKEN_CHARACTERS_PER_SECOND
        ]
        if overlong_scenes:
            details = ", ".join(
                f"{scene_id}（{actual}/{limit} 字，重写目标≤{target} 字）"
                for scene_id, actual, limit, target in overlong_scenes
            )
            raise ScreenwriterOutputError(
                "以下场景的旁白与对白超出时长可承载的口播预算：" + details
            )

    @staticmethod
    def _spoken_character_count(narration: str, dialogue: str) -> int:
        """以非空白字符近似口播长度；这是生成前的保守节奏门槛，不是配音计费。"""
        return len("".join((narration + dialogue).split()))

    def _report(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)
