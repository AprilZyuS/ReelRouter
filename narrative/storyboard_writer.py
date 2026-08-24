"""将已批准剧本拆解为带场景和原文证据的镜头清单。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol

from pydantic import ValidationError

from narrative.schemas import ContextPack, Screenplay, Storyboard
from video.schemas import VideoModelProfile


class StoryboardClient(Protocol):
    def generate(self, *, system_prompt: str, user_prompt: str) -> str: ...


class StoryboardOutputError(ValueError):
    """模型分镜没有通过结构、时长或证据校验时抛出。"""


class StoryboardVideoConstraints:
    """由当前视频模型能力导出的分镜限制，避免生成不可执行的镜头。"""

    def __init__(
        self,
        *,
        min_duration_seconds: int = 2,
        max_duration_seconds: int = 10,
        min_shot_count: int = 6,
        max_shot_count: int = 12,
    ) -> None:
        if min_duration_seconds < 2 or max_duration_seconds < min_duration_seconds:
            raise ValueError("分镜视频时长约束无效。")
        if min_shot_count < 3 or max_shot_count < min_shot_count:
            raise ValueError("分镜镜头数量约束无效。")
        self.min_duration_seconds = min_duration_seconds
        self.max_duration_seconds = max_duration_seconds
        self.min_shot_count = min_shot_count
        self.max_shot_count = max_shot_count

    @classmethod
    def from_video_models(
        cls,
        models: tuple[VideoModelProfile, ...],
        *,
        target_duration_seconds: int,
    ) -> "StoryboardVideoConstraints":
        if not models:
            raise ValueError("当前视频 Provider 没有可用模型。")
        minimum = min(model.min_duration_seconds for model in models)
        maximum = min(10, max(model.max_duration_seconds for model in models))
        max_shots = min(12, target_duration_seconds // minimum)
        min_shots = min(6, max_shots)
        if max_shots < 3:
            raise ValueError(
                f"目标时长 {target_duration_seconds} 秒不足以满足当前视频模型的最短 "
                f"{minimum} 秒镜头约束。"
            )
        return cls(
            min_duration_seconds=minimum,
            max_duration_seconds=maximum,
            min_shot_count=min_shots,
            max_shot_count=max_shots,
        )


class StoryboardWriter:
    """LLM 只拆镜头；项目、时长和剧本场景归属由代码复核。"""

    def __init__(self, client: StoryboardClient, *, max_format_retries: int = 1, progress_callback: Callable[[str], None] | None = None) -> None:
        if max_format_retries < 0:
            raise ValueError("max_format_retries 不能小于 0。")
        self.client, self.max_format_retries, self.progress_callback = client, max_format_retries, progress_callback

    def create(
        self,
        context: ContextPack,
        screenplay: Screenplay,
        *,
        video_constraints: StoryboardVideoConstraints | None = None,
    ) -> Storyboard:
        if (screenplay.project_id, screenplay.episode_number, screenplay.target_duration_seconds) != (context.episode.project_id, context.episode.episode_number, context.episode.target_duration_seconds):
            raise ValueError("Screenplay 必须与 Context Pack 属于同一集且时长一致。")
        constraints = video_constraints or StoryboardVideoConstraints()
        prompt = self._user_prompt(context, screenplay, constraints)
        for attempt in range(self.max_format_retries + 1):
            try:
                payload = self._parse(self.client.generate(system_prompt=self._system_prompt(constraints), user_prompt=prompt))
                result = Storyboard.model_validate({"project_id": screenplay.project_id, "episode_number": screenplay.episode_number, "target_duration_seconds": screenplay.target_duration_seconds, "shots": payload.get("shots")})
                self._validate(result, screenplay, context, constraints)
                return result
            except ValidationError as error:
                failure = self._build_contract_error(error)
                failure.__cause__ = error
            except StoryboardOutputError as error:
                failure = error
            if attempt == self.max_format_retries:
                raise failure
            self._report(f"Storyboard 输出未通过 JSON/业务校验，正在进行第 {attempt + 1} 次格式修复重试。")
            prompt += "\n\n上一版输出未通过校验：" + str(failure) + "。请完整重写，只返回合法 JSON。"
        raise AssertionError("不可达")

    @staticmethod
    def _system_prompt(constraints: StoryboardVideoConstraints) -> str:
        return f"""你是短剧分镜 Agent。只能把给定剧本拆为镜头，不得新增剧情。
只返回 JSON 对象，不能输出 Markdown、解释或额外字段。shots 必须有 {constraints.min_shot_count} 到 {constraints.max_shot_count} 项；每项且只能有 shot_id、scene_id、order、visual_prompt、camera_instruction、duration_seconds、source_chunk_ids。镜头顺序连续，单镜头 {constraints.min_duration_seconds}-{constraints.max_duration_seconds} 秒，时长总和严格等于目标时长。scene_id 与 source_chunk_ids 只能引用输入剧本和 Context Pack 已给出的值。

每个 shots 元素必须遵循此 JSON 形状：
{{"shot_id":"shot-001","scene_id":"scene-001","order":1,"visual_prompt":"可拍摄的画面描述","camera_instruction":"镜头语言","duration_seconds":{constraints.min_duration_seconds},"source_chunk_ids":["输入中存在的 chunk_id"]}}"""

    @staticmethod
    def _user_prompt(
        context: ContextPack,
        screenplay: Screenplay,
        constraints: StoryboardVideoConstraints,
    ) -> str:
        return json.dumps({"episode": context.episode.model_dump(), "style_bible": context.style_bible, "screenplay": screenplay.model_dump(), "source_chunk_ids": [chunk.chunk_id for chunk in context.source_chunks], "video_generation_constraints": {"min_shot_duration_seconds": constraints.min_duration_seconds, "max_shot_duration_seconds": constraints.max_duration_seconds, "min_shot_count": constraints.min_shot_count, "max_shot_count": constraints.max_shot_count}}, ensure_ascii=False, indent=2)

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
    def _build_contract_error(error: ValidationError) -> StoryboardOutputError:
        """把结构错误缩减为字段路径和原因，供模型重试与 UI 定位。"""

        details: list[str] = []
        for issue in error.errors(include_url=False):
            location = ".".join(str(item) for item in issue.get("loc", ()))
            message = str(issue.get("msg", "字段不符合要求"))
            details.append(f"{location}：{message}" if location else message)
        suffix = "；".join(details[:6])
        message = "模型返回的分镜不符合 Storyboard 数据契约。"
        if suffix:
            message += " 缺失或无效字段：" + suffix
        return StoryboardOutputError(message)

    @staticmethod
    def _validate(
        storyboard: Storyboard,
        screenplay: Screenplay,
        context: ContextPack,
        constraints: StoryboardVideoConstraints,
    ) -> None:
        if not constraints.min_shot_count <= len(storyboard.shots) <= constraints.max_shot_count:
            raise StoryboardOutputError(
                f"当前视频模型要求分镜镜头数为 {constraints.min_shot_count} 到 "
                f"{constraints.max_shot_count} 项。"
            )
        invalid_duration_shots = [
            shot.shot_id
            for shot in storyboard.shots
            if not constraints.min_duration_seconds
            <= shot.duration_seconds
            <= constraints.max_duration_seconds
        ]
        if invalid_duration_shots:
            raise StoryboardOutputError(
                f"当前视频模型要求每个镜头为 {constraints.min_duration_seconds}-"
                f"{constraints.max_duration_seconds} 秒；不符合的镜头："
                + ", ".join(invalid_duration_shots)
            )
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
