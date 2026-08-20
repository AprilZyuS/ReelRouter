"""长文本分集视频改编的校验数据契约。"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ShotImportance(str, Enum):
    """镜头的叙事重要程度决定其最低视觉质量要求。"""

    KEY = "key"
    STANDARD = "standard"


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


class EpisodePlan(BaseModel):
    """单集改编计划，以及支撑该集的原文章节范围。"""

    model_config = ConfigDict(frozen=True)

    project_id: str = Field(min_length=1, max_length=64)
    episode_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    source_chapter_start: int = Field(ge=1)
    source_chapter_end: int = Field(ge=1)
    target_duration_seconds: int = Field(ge=15, le=60)

    @model_validator(mode="after")
    def validate_chapter_range(self) -> "EpisodePlan":
        if self.source_chapter_end < self.source_chapter_start:
            raise ValueError("source_chapter_end 不能小于 source_chapter_start。")
        return self


class StoryDraft(BaseModel):
    """Story Writer 生成的、带原文证据的单集故事草稿。"""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=120)
    logline: str = Field(min_length=1, max_length=300)
    story_text: str = Field(min_length=80, max_length=3000)
    style_bible: str = Field(min_length=1, max_length=1000)
    source_chunk_ids: list[str] = Field(min_length=1, max_length=12)


class ScreenplayScene(BaseModel):
    """由故事草稿生成、尚未拆分为镜头的剧本场景。"""

    model_config = ConfigDict(frozen=True)

    scene_id: str = Field(min_length=1, max_length=64)
    order: int = Field(ge=1)
    narration: str = Field(min_length=1, max_length=1200)
    dialogue: str = Field(default="", max_length=1200)
    visual_description: str = Field(min_length=1, max_length=1600)
    duration_seconds: int = Field(ge=2, le=15)


class Screenplay(BaseModel):
    """一个单集内按顺序排列的剧本场景列表。"""

    model_config = ConfigDict(frozen=True)

    scenes: list[ScreenplayScene] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_scene_order(self) -> "Screenplay":
        scene_ids = [scene.scene_id for scene in self.scenes]
        orders = [scene.order for scene in self.scenes]
        if len(set(scene_ids)) != len(scene_ids):
            raise ValueError("screenplay 中 scene_id 不能重复。")
        if orders != list(range(1, len(self.scenes) + 1)):
            raise ValueError("screenplay 场景 order 必须从 1 连续递增。")
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


class PrioritizedShot(StoryboardShot):
    """由优先级 Agent 补全信息、供视频模型路由使用的镜头。"""

    importance: ShotImportance
    priority_reason: str = Field(min_length=1, max_length=500)
    min_quality_score: int = Field(ge=1, le=10)

    @model_validator(mode="after")
    def validate_key_shot_quality(self) -> "PrioritizedShot":
        if self.importance == ShotImportance.KEY and self.min_quality_score < 7:
            raise ValueError("关键镜头的 min_quality_score 必须不低于 7。")
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
