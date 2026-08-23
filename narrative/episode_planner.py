"""将已入库小说拆成可追溯的分集计划。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol

from pydantic import ValidationError

from narrative.repository import NarrativeKnowledgeRepository
from narrative.schemas import EpisodePlanSet, NarrativeProjectRequest


class EpisodePlannerClient(Protocol):
    """Episode Planner 需要的最小模型客户端能力。"""

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        """接收提示词并返回模型原始文本。"""
        ...


class EpisodePlannerOutputError(ValueError):
    """模型输出不是可信分集计划时抛出。"""


class EpisodePlanner:
    """让模型规划分集，再以数据库中的原文和项目约束校验结果。

    Planner 不直接写数据库。Day 2 会把通过校验的计划持久化；当前类仅负责
    将不可信的模型文本转换为可信的 ``EpisodePlanSet``。
    """

    def __init__(
        self,
        client: EpisodePlannerClient,
        repository: NarrativeKnowledgeRepository,
        *,
        max_format_retries: int = 1,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        if max_format_retries < 0:
            raise ValueError("max_format_retries 不能小于 0。")
        self.client = client
        self.repository = repository
        self.max_format_retries = max_format_retries
        self.progress_callback = progress_callback

    def plan(
        self,
        request: NarrativeProjectRequest,
        *,
        episode_count: int = 2,
    ) -> EpisodePlanSet:
        """为当前小说稿生成指定数量的连续计划，默认只规划 v1 的前两集。"""
        if not 1 <= episode_count <= 20:
            raise ValueError("episode_count 必须在 1 到 20 之间。")

        profile = self.repository.get_project_profile(request.project_id)
        if profile is None:
            raise LookupError(
                f"项目 {request.project_id} 不存在 NarrativeProjectProfile。"
            )

        chunks = self.repository.list_chunks(profile.manuscript_document_id)
        if not chunks:
            raise LookupError(
                f"项目 {request.project_id} 的小说稿没有可用于规划的原文分块。"
            )

        allowed_chunk_ids = {chunk.chunk_id for chunk in chunks}
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            request,
            profile_title=profile.title,
            profile_logline=profile.logline,
            style_bible=profile.style_bible,
            chunks=chunks,
            episode_count=episode_count,
        )

        for attempt in range(self.max_format_retries + 1):
            raw_response = self.client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            try:
                payload = self._parse_json_object(raw_response)

                # project_id 是系统事实，绝不接受模型伪造或串项目的值。
                payload["project_id"] = request.project_id
                self._assign_system_project_id(payload, request.project_id)
                result = EpisodePlanSet.model_validate(payload)
                self._validate_business_rules(
                    result,
                    requested_episode_count=episode_count,
                    requested_duration_seconds=request.episode_duration_seconds,
                    allowed_chunk_ids=allowed_chunk_ids,
                )
                return result
            except ValidationError as error:
                output_error = EpisodePlannerOutputError(
                    "模型返回的分集计划不符合 EpisodePlanSet 数据契约。"
                )
                output_error.__cause__ = error
            except EpisodePlannerOutputError as error:
                output_error = error

            if attempt == self.max_format_retries:
                raise output_error

            self._report(
                "Episode Planner 输出未通过 JSON/业务校验，"
                f"正在进行第 {attempt + 1} 次格式修复重试。"
            )
            user_prompt = self._build_retry_user_prompt(
                original_prompt=user_prompt,
                error=output_error,
            )

        raise AssertionError("不可达：循环会在成功返回或最后一次失败时结束。")

    @staticmethod
    def _build_system_prompt() -> str:
        return """你是中文短剧分集规划 Agent。
你必须严格依据用户提供的项目资料和原文分块，将故事拆分为连续的分集计划。

只返回一个合法 JSON 对象，不能使用 Markdown 代码块，不能添加解释文字。
JSON 必须且只能包含以下字段：
- project_id: 字符串
- plans: 数组。每个元素必须且只能包含：episode_number、title、
  source_chapter_start、source_chapter_end、target_duration_seconds、
  episode_goal、closing_hook、source_chunk_ids、scope。

规则：
1. plans 数量必须严格等于用户要求的数量，episode_number 必须从 1 连续递增。
2. 每集 target_duration_seconds 必须严格等于用户提供的目标时长。
3. source_chunk_ids 只能引用用户提供的“可引用原文分块 ID”，每集至少引用一个。
4. 不得补写原文中不存在的人物、事件或结局；将悬念放在 closing_hook。
5. scope 必须且只能包含 must_include、must_defer、ending_beat：
   - must_include 写本集必须推进的 1 至 6 个剧情节点；
   - must_defer 写后续集才可展开的剧情节点；
   - ending_beat 必须与 closing_hook 表达同一停点。
   不要把故事专有名词硬编码成规则，应依据本项目原文填写。
6. JSON 内的字符串必须进行合法转义，并在结束前闭合所有引号、方括号和花括号。"""

    @staticmethod
    def _build_user_prompt(
        request: NarrativeProjectRequest,
        *,
        profile_title: str,
        profile_logline: str,
        style_bible: str,
        chunks: object,
        episode_count: int,
    ) -> str:
        # chunks 是 DocumentChunk 的序列；只发送当前小说稿，避免跨项目串文。
        source_chunks = [
            {
                "chunk_id": chunk.chunk_id,
                "chapter_number": chunk.chapter_number,
                "content": chunk.content,
            }
            for chunk in chunks
        ]
        planning_input = {
            "项目标题": profile_title,
            "故事梗概": profile_logline,
            "风格设定": style_bible,
            "用户关键词": request.keywords,
            "必须规划的集数": episode_count,
            "每集目标时长（秒）": request.episode_duration_seconds,
            "可引用原文分块": source_chunks,
        }
        return "请基于以下资料规划分集：\n" + json.dumps(
            planning_input,
            ensure_ascii=False,
            indent=2,
        )

    @staticmethod
    def _build_retry_user_prompt(
        *,
        original_prompt: str,
        error: EpisodePlannerOutputError,
    ) -> str:
        return (
            original_prompt
            + "\n\n上一版输出未通过校验："
            + str(error)
            + "\n请完整重写，不能续写或解释。只返回一个可被 json.loads 解析的 JSON 对象。"
        )

    @staticmethod
    def _parse_json_object(raw_response: str) -> dict[str, object]:
        try:
            payload = json.loads(raw_response.strip())
        except json.JSONDecodeError as error:
            raise EpisodePlannerOutputError(
                "模型返回的内容不是合法 JSON；"
                f"响应字符数：{len(raw_response.strip())}，解析原因：{error.msg}。"
            ) from error
        if not isinstance(payload, dict):
            raise EpisodePlannerOutputError("模型返回的 JSON 顶层必须是对象。")
        return payload

    @staticmethod
    def _assign_system_project_id(
        payload: dict[str, object],
        project_id: str,
    ) -> None:
        """为每个单集注入系统拥有的 project_id。

        模型输出只需描述分集本身；领域模型中的 EpisodePlan 仍保留 project_id，
        使其脱离 EpisodePlanSet 被持久化或单独传递时也不会丢失归属。
        """
        plans = payload.get("plans")
        if not isinstance(plans, list):
            return
        for plan in plans:
            if isinstance(plan, dict):
                plan["project_id"] = project_id

    @staticmethod
    def _validate_business_rules(
        result: EpisodePlanSet,
        *,
        requested_episode_count: int,
        requested_duration_seconds: int,
        allowed_chunk_ids: set[str],
    ) -> None:
        if len(result.plans) != requested_episode_count:
            raise EpisodePlannerOutputError(
                "模型返回的 plans 数量与请求的 episode_count 不一致。"
            )

        wrong_duration_numbers = [
            str(plan.episode_number)
            for plan in result.plans
            if plan.target_duration_seconds != requested_duration_seconds
        ]
        if wrong_duration_numbers:
            raise EpisodePlannerOutputError(
                "以下集的 target_duration_seconds 与请求不一致："
                + ", ".join(wrong_duration_numbers)
            )

        unknown_chunk_ids = sorted(
            {
                chunk_id
                for plan in result.plans
                for chunk_id in plan.source_chunk_ids
                if chunk_id not in allowed_chunk_ids
            }
        )
        if unknown_chunk_ids:
            raise EpisodePlannerOutputError(
                "模型引用了当前小说稿不存在的 source_chunk_ids："
                + ", ".join(unknown_chunk_ids)
            )

        missing_scope_numbers = [
            str(plan.episode_number)
            for plan in result.plans
            if plan.scope is None
        ]
        if missing_scope_numbers:
            raise EpisodePlannerOutputError(
                "以下集缺少用于 Writer/Reviewer 的 scope："
                + ", ".join(missing_scope_numbers)
            )

    def _report(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)
