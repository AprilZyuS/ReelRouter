"""长文本分集视频改编的校验数据契约。"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ShotImportance(str, Enum):
    """镜头的叙事重要程度决定其最低视觉质量要求。"""

    KEY = "key"
    STANDARD = "standard"


class ScreenplayCandidateStatus(str, Enum):
    """候选剧本在进入正式长期记忆前的生命周期。"""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class NarrativeProjectRequest(BaseModel):
    """一个分集视频项目的创作与预算约束。"""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    keywords: list[str] = Field(min_length=1, max_length=8)
    genre: str = Field(min_length=1, max_length=80)
    visual_style: str = Field(min_length=1, max_length=200)
    episode_duration_seconds: int = Field(ge=15, le=60)
    episode_budget_usd: float = Field(gt=0)
    enable_assembly: bool = True

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, keywords: list[str]) -> list[str]:
        """去除关键词两侧空白，并拒绝重复或空白关键词。"""
        normalized = [keyword.strip() for keyword in keywords]
        if any(not keyword for keyword in normalized):
            raise ValueError("keywords 不能包含空字符串。")
        if len(set(normalized)) != len(normalized):
            raise ValueError("keywords 不能重复。")
        return normalized

class NovelManuscript(BaseModel):
    """Story Writer 根据用户创作要求生成的原始小说稿。"""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    logline: str = Field(min_length=1, max_length=300)
    manuscript: str = Field(min_length=800, max_length=12_000)
    style_bible: str = Field(min_length=1, max_length=1000)
    planned_episode_count: int = Field(ge=2, le=20)


class EpisodeScope(BaseModel):
    """Planner 为一集划出的剧情边界，供 Writer 与 Reviewer 共同遵守。

    这是业务数据而不是针对某个故事硬编码的关键词列表。它允许每个项目由
    Planner 描述本集应推进什么、必须留到后续什么，以及应停在什么悬念上。
    """

    model_config = ConfigDict(frozen=True)

    must_include: list[str] = Field(min_length=1, max_length=6)
    must_defer: list[str] = Field(default_factory=list, max_length=6)
    ending_beat: str = Field(min_length=1, max_length=500)

    @field_validator("must_include", "must_defer")
    @classmethod
    def normalize_beats(cls, beats: list[str]) -> list[str]:
        normalized = [beat.strip() for beat in beats]
        if any(not beat for beat in normalized):
            raise ValueError("剧情节点不能包含空字符串。")
        if len(set(normalized)) != len(normalized):
            raise ValueError("剧情节点不能重复。")
        return normalized


class EpisodePlan(BaseModel):
    """单集改编计划，以及支撑该集的原文章节与可回溯分块证据。"""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    episode_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    source_chapter_start: int = Field(ge=1)
    source_chapter_end: int = Field(ge=1)
    target_duration_seconds: int = Field(ge=15, le=60)

    episode_goal: str = Field(min_length=1, max_length=500)
    closing_hook: str = Field(min_length=1, max_length=500)
    source_chunk_ids: list[str] = Field(min_length=1, max_length=8)
    # None 用于兼容旧项目；新 Planner 必须生成该字段。
    scope: EpisodeScope | None = None

    @model_validator(mode="after")
    def validate_chapter_range(self) -> "EpisodePlan":
        if self.source_chapter_end < self.source_chapter_start:
            raise ValueError("source_chapter_end 不能小于 source_chapter_start。")
        return self

    @field_validator("source_chunk_ids")
    @classmethod
    def normalize_source_chunk_ids(cls, chunk_ids: list[str]) -> list[str]:
        """保留可追溯证据的稳定 ID，并拒绝空值和重复引用。"""
        normalized = [chunk_id.strip() for chunk_id in chunk_ids]
        if any(not chunk_id for chunk_id in normalized):
            raise ValueError("source_chunk_ids 不能包含空字符串。")
        if len(set(normalized)) != len(normalized):
            raise ValueError("source_chunk_ids 不能重复。")
        return normalized


class StoryDraft(BaseModel):
    """Story Writer 生成的、带原文证据的单集故事草稿。"""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=120)
    logline: str = Field(min_length=1, max_length=300)
    story_text: str = Field(min_length=80, max_length=3000)
    style_bible: str = Field(min_length=1, max_length=1000)
    source_chunk_ids: list[str] = Field(min_length=1, max_length=12)


class ScreenplayScene(BaseModel):
    """由 Context Pack 生成、尚未拆分为镜头的剧本场景。"""

    model_config = ConfigDict(frozen=True)

    scene_id: str = Field(min_length=1, max_length=64)
    order: int = Field(ge=1)
    narration: str = Field(min_length=1, max_length=1200)
    dialogue: str = Field(default="", max_length=1200)
    visual_description: str = Field(min_length=1, max_length=1600)
    duration_seconds: int = Field(ge=2, le=15)
    source_chunk_ids: list[str] = Field(min_length=1, max_length=8)

    @field_validator("source_chunk_ids")
    @classmethod
    def normalize_source_chunk_ids(cls, chunk_ids: list[str]) -> list[str]:
        """每个场景都必须标明可回溯的原文证据。"""
        normalized = [chunk_id.strip() for chunk_id in chunk_ids]
        if any(not chunk_id for chunk_id in normalized):
            raise ValueError("source_chunk_ids 不能包含空字符串。")
        if len(set(normalized)) != len(normalized):
            raise ValueError("source_chunk_ids 不能重复。")
        return normalized


class Screenplay(BaseModel):
    """一个带时长和原文证据约束的单集剧本。"""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    episode_number: int = Field(ge=1)
    target_duration_seconds: int = Field(ge=15, le=60)
    scenes: list[ScreenplayScene] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_scene_order(self) -> "Screenplay":
        scene_ids = [scene.scene_id for scene in self.scenes]
        orders = [scene.order for scene in self.scenes]
        if len(set(scene_ids)) != len(scene_ids):
            raise ValueError("screenplay 中 scene_id 不能重复。")
        if orders != list(range(1, len(self.scenes) + 1)):
            raise ValueError("screenplay 场景 order 必须从 1 连续递增。")
        if sum(scene.duration_seconds for scene in self.scenes) != self.target_duration_seconds:
            raise ValueError("screenplay 场景时长之和必须等于 target_duration_seconds。")
        return self


class ScreenplayReview(BaseModel):
    """Reviewer 对候选剧本给出的结构化结论。

    passed 只表示自动审查建议可以进入人工批准，不等于模型自行发布剧本。
    """

    model_config = ConfigDict(frozen=True)

    passed: bool
    feedback: str = Field(min_length=1, max_length=2000)
    violations: list[str] = Field(default_factory=list, max_length=12)
    episode_summary: "EpisodeSummary | None" = None

    @model_validator(mode="after")
    def validate_review_outcome(self) -> "ScreenplayReview":
        if self.passed and self.episode_summary is None:
            raise ValueError("通过的剧本审查必须生成 EpisodeSummary。")
        if not self.passed and self.episode_summary is not None:
            raise ValueError("未通过的剧本审查不能写入 EpisodeSummary。")
        return self


class ScreenplayCandidate(BaseModel):
    """一份可审查、可追溯、但尚未替换正式剧本的候选稿。"""

    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(min_length=1, max_length=64)
    screenplay: Screenplay
    status: ScreenplayCandidateStatus = ScreenplayCandidateStatus.DRAFT
    review: ScreenplayReview | None = None

    @model_validator(mode="after")
    def validate_candidate_status(self) -> "ScreenplayCandidate":
        if self.status == ScreenplayCandidateStatus.DRAFT and self.review is not None:
            raise ValueError("draft 候选稿不能带有审查结果。")
        if self.status in {
            ScreenplayCandidateStatus.REVIEWED,
            ScreenplayCandidateStatus.APPROVED,
            ScreenplayCandidateStatus.REJECTED,
        } and self.review is None:
            raise ValueError("已审查或已决定的候选稿必须带有审查结果。")
        if self.status == ScreenplayCandidateStatus.APPROVED and not self.review.passed:
            raise ValueError("未通过 Reviewer 的候选稿不能被批准。")
        if self.status == ScreenplayCandidateStatus.REJECTED and self.review.passed:
            raise ValueError("通过 Reviewer 的候选稿不能标记为 rejected。")
        return self


class StoryboardShot(BaseModel):
    """尚未被赋予叙事重要程度的视觉镜头。"""

    model_config = ConfigDict(frozen=True)

    shot_id: str = Field(min_length=1, max_length=64)
    scene_id: str = Field(min_length=1, max_length=64)
    order: int = Field(ge=1)
    visual_prompt: str = Field(min_length=1, max_length=2000)
    camera_instruction: str = Field(min_length=1, max_length=500)
    duration_seconds: int = Field(ge=2, le=10)
    source_chunk_ids: list[str] = Field(min_length=1, max_length=8)

    @field_validator("source_chunk_ids")
    @classmethod
    def normalize_source_chunk_ids(cls, chunk_ids: list[str]) -> list[str]:
        normalized = [chunk_id.strip() for chunk_id in chunk_ids]
        if any(not chunk_id for chunk_id in normalized):
            raise ValueError("source_chunk_ids 不能包含空字符串。")
        if len(set(normalized)) != len(normalized):
            raise ValueError("source_chunk_ids 不能重复。")
        return normalized


class Storyboard(BaseModel):
    """已批准剧本对应的、按时间顺序排列的镜头清单。"""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    episode_number: int = Field(ge=1)
    target_duration_seconds: int = Field(ge=15, le=60)
    # 少于 24 秒的单集可能无法同时满足“至少 6 镜头”和某些 Provider 的最短镜头限制；
    # 具体数量由 StoryboardVideoConstraints 按当前模型能力进一步收紧。
    shots: list[StoryboardShot] = Field(min_length=3, max_length=12)

    @model_validator(mode="after")
    def validate_shot_sequence(self) -> "Storyboard":
        shot_ids = [shot.shot_id for shot in self.shots]
        orders = [shot.order for shot in self.shots]
        if len(set(shot_ids)) != len(shot_ids):
            raise ValueError("storyboard 中 shot_id 不能重复。")
        if orders != list(range(1, len(self.shots) + 1)):
            raise ValueError("storyboard 镜头 order 必须从 1 连续递增。")
        if sum(shot.duration_seconds for shot in self.shots) != self.target_duration_seconds:
            raise ValueError("storyboard 镜头时长之和必须等于 target_duration_seconds。")
        return self


class PrioritizedShot(StoryboardShot):
    """由优先级 Agent 补全信息、供视频模型路由使用的镜头。"""

    importance: ShotImportance
    priority_reason: str = Field(min_length=1, max_length=500)
    min_quality_score: int = Field(ge=1, le=10)

    @model_validator(mode="after")
    def validate_key_shot_quality(self) -> "PrioritizedShot":
        if self.importance == ShotImportance.KEY and self.min_quality_score < 7:
            raise ValueError("关键镜头的 min_quality_score 必须不低于 7。")
        if self.importance == ShotImportance.STANDARD and self.min_quality_score > 6:
            raise ValueError("普通镜头的 min_quality_score 不能高于 6。")
        return self


class PrioritizedStoryboard(BaseModel):
    """附带成本路由约束的镜头清单。"""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    episode_number: int = Field(ge=1)
    target_duration_seconds: int = Field(ge=15, le=60)
    shots: list[PrioritizedShot] = Field(min_length=3, max_length=12)

    @model_validator(mode="after")
    def validate_prioritized_sequence(self) -> "PrioritizedStoryboard":
        if [shot.order for shot in self.shots] != list(range(1, len(self.shots) + 1)):
            raise ValueError("prioritized storyboard 镜头 order 必须连续递增。")
        if sum(shot.duration_seconds for shot in self.shots) != self.target_duration_seconds:
            raise ValueError("prioritized storyboard 镜头时长之和必须等于 target_duration_seconds。")
        return self


class CharacterProfile(BaseModel):
    """创建角色视觉资产前使用的、不可随意变更的文本身份设定。"""

    model_config = ConfigDict(frozen=True)

    character_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    canonical_description: str = Field(min_length=1, max_length=1500)
    immutable_traits: list[str] = Field(min_length=1, max_length=12)
    evidence_chunk_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("immutable_traits")
    @classmethod
    def normalize_traits(cls, traits: list[str]) -> list[str]:
        normalized = [trait.strip() for trait in traits]
        if any(not trait for trait in normalized):
            raise ValueError("immutable_traits 不能包含空字符串。")
        return normalized


class SourceChunk(BaseModel):
    """为某一集检索出的、可作为显式证据的原文片段。"""

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=1, max_length=64)
    chapter_number: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=4000)
    relevance_score: float = Field(ge=0, le=1)


class EpisodeSummary(BaseModel):
    """只有通过剧情一致性审核后才能写入的分集长期记忆。"""

    model_config = ConfigDict(frozen=True)

    episode_number: int = Field(ge=1)
    recap: str = Field(min_length=1, max_length=1600)
    unresolved_loops: list[str] = Field(default_factory=list, max_length=12)


class ContextPack(BaseModel):
    """提供给当前单集所有叙事 Agent 的受控上下文包。"""

    model_config = ConfigDict(frozen=True)

    episode: EpisodePlan
    source_chunks: list[SourceChunk] = Field(min_length=1, max_length=8)
    characters: list[CharacterProfile] = Field(default_factory=list, max_length=2)
    canonical_facts: list[str] = Field(default_factory=list, max_length=20)
    previous_episode_summary: EpisodeSummary | None = None
    style_bible: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_episode_memory(self) -> "ContextPack":
        chunk_ids = [chunk.chunk_id for chunk in self.source_chunks]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("ContextPack 的 source_chunks 不能包含重复 chunk_id。")
        if self.episode.episode_number == 1 and self.previous_episode_summary is not None:
            raise ValueError("第 1 集不能包含 previous_episode_summary。")
        if (
            self.episode.episode_number > 1
            and self.previous_episode_summary is None
        ):
            raise ValueError("第 2 集及之后必须包含 previous_episode_summary。")
        return self

class NarrativeDocument(BaseModel):
    """用户导入的原始长文本，尚未进行分块或向量化。"""

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    source_type: Literal["text", "markdown"]
    # 保留原始文本，不 strip；否则后续字符位置无法精确回指原文。
    raw_text: str = Field(min_length=1, max_length=2_000_000)

    @field_validator("raw_text")
    @classmethod
    def reject_blank_raw_text(cls, raw_text: str) -> str:
        """拒绝仅由空白字符组成的“伪文本”。"""
        if not raw_text.strip():
            raise ValueError("raw_text 不能只包含空白字符。")
        return raw_text


class DocumentChunk(BaseModel):
    """持久化保存的原文分块，携带可回溯的字符位置。"""

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=1, max_length=80)
    document_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)
    chapter_number: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_character_range(self) -> "DocumentChunk":
        """确保位置区间有效，并与保存内容的字符长度一致。"""
        if self.end_char <= self.start_char:
            raise ValueError("end_char 必须大于 start_char。")
        if len(self.content) != self.end_char - self.start_char:
            raise ValueError("content 长度必须与字符位置区间一致。")
        return self

class NarrativeProjectProfile(BaseModel):
    """一个项目在跨 Agent 协作中持续有效的叙事事实。"""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    manuscript_document_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    logline: str = Field(min_length=1, max_length=300)
    style_bible: str = Field(min_length=1, max_length=1000)
    planned_episode_count: int = Field(ge=2, le=20)
    # 保留创作请求，使后续 Planner 不必伪造关键词、题材与预算。
    keywords: list[str] = Field(default_factory=list, max_length=8)
    genre: str = Field(default="未指定", min_length=1, max_length=80)
    episode_duration_seconds: int = Field(default=45, ge=15, le=60)
    episode_budget_usd: float = Field(default=1.0, gt=0)
    enable_assembly: bool = True
    narrative_version: int = Field(default=1, ge=1)

class EpisodePlanSet(BaseModel):
    """同一项目的一组连续分集计划，供 Context Manager 逐集执行。"""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    plans: list[EpisodePlan] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_plans(self) -> "EpisodePlanSet":
        if any(plan.project_id != self.project_id for plan in self.plans):
            raise ValueError("EpisodePlanSet 中所有计划的 project_id 必须一致。")

        episode_numbers = [plan.episode_number for plan in self.plans]
        expected_numbers = list(range(1, len(self.plans) + 1))
        if episode_numbers != expected_numbers:
            raise ValueError("EpisodePlanSet 的 episode_number 必须从 1 连续递增。")
        return self
