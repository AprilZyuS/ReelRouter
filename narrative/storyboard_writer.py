"""将已批准剧本拆解为带场景和原文证据的镜头清单。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol

from pydantic import ValidationError

from narrative.schemas import ContextPack, Screenplay, Storyboard


class StoryboardClient(Protocol):
    def generate(self, *, system_prompt: str, user_prompt: str) -> str: ...


class StoryboardOutputError(ValueError):
    """模型分镜没有通过结构、时长或证据校验时抛出。"""


class StoryboardWriter:
    """LLM 只拆镜头；项目、时长和剧本场景归属由代码复核。"""

    def __init__(self, client: StoryboardClient, *, max_format_retries: int = 1, progress_callback: Callable[[str], None] | None = None) -> None:
        if max_format_retries < 0:
            raise ValueError("max_format_retries 不能小于 0。")
        self.client, self.max_format_retries, self.progress_callback = client, max_format_retries, progress_callback

    def create(self, context: ContextPack, screenplay: Screenplay) -> Storyboard:
        if (screenplay.project_id, screenplay.episode_number, screenplay.target_duration_seconds) != (context.episode.project_id, context.episode.episode_number, context.episode.target_duration_seconds):
            raise ValueError("Screenplay 必须与 Context Pack 属于同一集且时长一致。")
        prompt = self._user_prompt(context, screenplay)
        for attempt in range(self.max_format_retries + 1):
            try:
                payload = self._parse(self.client.generate(system_prompt=self._system_prompt(), user_prompt=prompt))
                result = Storyboard.model_validate({"project_id": screenplay.project_id, "episode_number": screenplay.episode_number, "target_duration_seconds": screenplay.target_duration_seconds, "shots": payload.get("shots")})
                self._validate(result, screenplay, context)
                return result
            except ValidationError as error:
                failure = StoryboardOutputError("模型返回的分镜不符合 Storyboard 数据契约。")
                failure.__cause__ = error
            except StoryboardOutputError as error:
                failure = error
            if attempt == self.max_format_retries:
                raise failure
            self._report(f"Storyboard 输出未通过 JSON/业务校验，正在进行第 {attempt + 1} 次格式修复重试。")
            prompt += "\n\n上一版输出未通过校验：" + str(failure) + "。请完整重写，只返回合法 JSON。"
        raise AssertionError("不可达")

    @staticmethod
    def _system_prompt() -> str:
        return """你是短剧分镜 Agent。只能把给定剧本拆为镜头，不得新增剧情。只返回 JSON 对象 {\"shots\":[...]}。shots 必须有 6 到 12 项；每项且只能有 shot_id、scene_id、order、visual_prompt、camera_instruction、duration_seconds、source_chunk_ids。镜头顺序连续，单镜头 2-10 秒，时长总和严格等于目标时长。scene_id 与 source_chunk_ids 只能引用输入剧本和 Context Pack 已给出的值。"""

    @staticmethod
    def _user_prompt(context: ContextPack, screenplay: Screenplay) -> str:
        return json.dumps({"episode": context.episode.model_dump(), "style_bible": context.style_bible, "screenplay": screenplay.model_dump(), "source_chunk_ids": [chunk.chunk_id for chunk in context.source_chunks]}, ensure_ascii=False, indent=2)

    @staticmethod
    def _parse(raw: str) -> dict[str, object]:
        try:
            payload = json.loads(raw.strip())
        except json.JSONDecodeError as error:
            raise StoryboardOutputError("模型返回的内容不是合法 JSON。") from error
        if not isinstance(payload, dict):
            raise StoryboardOutputError("模型返回的 JSON 顶层必须是对象。")
        return payload

    @staticmethod
    def _validate(storyboard: Storyboard, screenplay: Screenplay, context: ContextPack) -> None:
        scenes = {scene.scene_id: scene for scene in screenplay.scenes}
        allowed_chunks = {chunk.chunk_id for chunk in context.source_chunks}
        for shot in storyboard.shots:
            scene = scenes.get(shot.scene_id)
            if scene is None:
                raise StoryboardOutputError(f"分镜引用了不存在的 scene_id：{shot.scene_id}。")
            if any(chunk_id not in allowed_chunks or chunk_id not in scene.source_chunk_ids for chunk_id in shot.source_chunk_ids):
                raise StoryboardOutputError(f"镜头 {shot.shot_id} 引用了不属于所属场景的 source_chunk_ids。")

    def _report(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)
