"""对候选剧本执行剧情边界与跨集一致性审查。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol

from pydantic import ValidationError

from narrative.schemas import ContextPack, Screenplay, ScreenplayReview


class ScreenplayReviewerClient(Protocol):
    """Reviewer 所需的最小模型接口，便于替换模型和编写无网络测试。"""

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        ...


class ScreenplayReviewOutputError(ValueError):
    """Reviewer 的结构化输出不可信或与候选剧本不匹配。"""


class ScreenplayReviewer:
    """用受控 Context Pack 审查候选稿，但不拥有发布权限。

    Reviewer 的职责是发现越过 EpisodeScope、提前揭示后续剧情、原文证据不足
    和跨集记忆冲突等问题。即便 passed=True，仍要经过人工批准才会进入长期记忆。
    """

    def __init__(
        self,
        client: ScreenplayReviewerClient,
        *,
        max_format_retries: int = 1,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        if max_format_retries < 0:
            raise ValueError("max_format_retries 不能小于 0。")
        self.client = client
        self.max_format_retries = max_format_retries
        self.progress_callback = progress_callback

    def review(self, context: ContextPack, screenplay: Screenplay) -> ScreenplayReview:
        """审查与 Context Pack 属于同一集的候选剧本。"""
        self._validate_input(context, screenplay)
        user_prompt = self._build_user_prompt(context, screenplay)

        for attempt in range(self.max_format_retries + 1):
            raw_response = self.client.generate(
                system_prompt=self._build_system_prompt(),
                user_prompt=user_prompt,
            )
            try:
                payload = self._parse_json_object(raw_response)
                result = ScreenplayReview.model_validate(payload)
                self._validate_result(result, context)
                return result
            except ValidationError as error:
                output_error = self._build_contract_error(error)
                output_error.__cause__ = error
            except ScreenplayReviewOutputError as error:
                output_error = error

            if attempt == self.max_format_retries:
                raise output_error
            self._report(
                "Screenplay Reviewer 输出未通过 JSON/业务校验，"
                f"正在进行第 {attempt + 1} 次格式修复重试。"
            )
            user_prompt += (
                "\n\n上一版审查输出无效："
                + str(output_error)
                + "。请完整重写，只返回合法 JSON。"
            )

        raise AssertionError("不可达")

    @staticmethod
    def _build_system_prompt() -> str:
        return """你是 ReelRouter 的剧情一致性 Reviewer，不负责重写剧本。
请依据 Context Pack、EpisodePlan 及其 scope 审查候选剧本：
1. 场景是否只使用本集 source_chunk_ids 支撑的事实；
2. 是否推进了 scope.must_include，并在 closing_hook / scope.ending_beat 停止；
3. 是否提前展开或解决 scope.must_defer；
4. 是否与角色、canonical_facts、上一集摘要冲突；
5. 是否保留可供下一集使用的未解线索。

只返回一个合法 JSON 对象，且只能有 passed、feedback、violations、episode_summary。
passed 为 true 时，episode_summary 必须包含 episode_number、recap、unresolved_loops，
其中 episode_number 必须等于正在审查的 episode.episode_number；
passed 为 false 时，episode_summary 必须为 null，且 violations 至少包含一项。

通过时的唯一 JSON 结构示例：
{"passed": true, "feedback": "本集边界清晰。", "violations": [], "episode_summary": {"episode_number": 1, "recap": "本集发生的事实。", "unresolved_loops": ["留给下一集的线索"]}}
不通过时的唯一 JSON 结构示例：
{"passed": false, "feedback": "本集提前揭示了后续真相。", "violations": ["提前解决 must_defer"], "episode_summary": null}
不要输出 Markdown 或解释文字。"""

    @staticmethod
    def _build_user_prompt(context: ContextPack, screenplay: Screenplay) -> str:
        return json.dumps(
            {
                "episode": context.episode.model_dump(),
                "source_chunks": [chunk.model_dump() for chunk in context.source_chunks],
                "characters": [item.model_dump() for item in context.characters],
                "canonical_facts": context.canonical_facts,
                "previous_episode_summary": (
                    context.previous_episode_summary.model_dump()
                    if context.previous_episode_summary is not None
                    else None
                ),
                "candidate_screenplay": screenplay.model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        )

    @staticmethod
    def _parse_json_object(raw_response: str) -> dict[str, object]:
        try:
            payload = json.loads(raw_response.strip())
        except json.JSONDecodeError as error:
            raise ScreenplayReviewOutputError("Reviewer 返回的内容不是合法 JSON。") from error
        if not isinstance(payload, dict):
            raise ScreenplayReviewOutputError("Reviewer 返回的 JSON 顶层必须是对象。")
        return payload

    @staticmethod
    def _build_contract_error(error: ValidationError) -> ScreenplayReviewOutputError:
        """仅输出字段路径和校验原因，便于模型重试与前端定位，不泄露原始响应。"""

        details: list[str] = []
        for issue in error.errors(include_url=False):
            location = ".".join(str(item) for item in issue.get("loc", ()))
            message = str(issue.get("msg", "字段不符合要求"))
            details.append(f"{location}：{message}" if location else message)
        suffix = "；".join(details[:6])
        message = "Reviewer 返回的内容不符合 ScreenplayReview 数据契约。"
        if suffix:
            message += " 缺失或无效字段：" + suffix
        return ScreenplayReviewOutputError(message)

    @staticmethod
    def _validate_input(context: ContextPack, screenplay: Screenplay) -> None:
        if (
            screenplay.project_id != context.episode.project_id
            or screenplay.episode_number != context.episode.episode_number
            or screenplay.target_duration_seconds
            != context.episode.target_duration_seconds
        ):
            raise ValueError("候选剧本必须与 Context Pack 属于同一项目、同一集且时长一致。")
        allowed_chunk_ids = set(context.episode.source_chunk_ids)
        invalid_ids = sorted(
            {
                chunk_id
                for scene in screenplay.scenes
                for chunk_id in scene.source_chunk_ids
                if chunk_id not in allowed_chunk_ids
            }
        )
        if invalid_ids:
            raise ValueError("候选剧本含有本集范围外的证据：" + ", ".join(invalid_ids))

    @staticmethod
    def _validate_result(result: ScreenplayReview, context: ContextPack) -> None:
        if result.passed and result.episode_summary is not None:
            if result.episode_summary.episode_number != context.episode.episode_number:
                raise ScreenplayReviewOutputError(
                    "Reviewer 的 EpisodeSummary 集号必须与候选剧本一致。"
                )
        if not result.passed and not result.violations:
            raise ScreenplayReviewOutputError(
                "未通过的 Reviewer 结论必须至少给出一项 violations。"
            )

    def _report(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)
