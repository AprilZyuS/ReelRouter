"""叙事领域数据契约的单元测试。"""

import pytest
from pydantic import ValidationError

from narrative.schemas import (
    CharacterProfile,
    ContextPack,
    EpisodePlan,
    EpisodeSummary,
    DocumentChunk,
    NarrativeDocument,
    NarrativeProjectRequest,
    PrioritizedShot,
    Screenplay,
    ScreenplayScene,
    ShotImportance,
    SourceChunk,
)


def make_episode(*, number: int = 1) -> EpisodePlan:
    return EpisodePlan(
        project_id="project-001",
        episode_number=number,
        title=f"第 {number} 集",
        source_chapter_start=number,
        source_chapter_end=number + 1,
        target_duration_seconds=45,
    )


def make_source_chunk(chunk_id: str = "chunk-001") -> SourceChunk:
    return SourceChunk(
        chunk_id=chunk_id,
        chapter_number=1,
        content="林舟在雨夜收到一封没有署名的信，信中提到失踪多年的姐姐。",
        relevance_score=0.93,
    )


def test_project_request_normalizes_keywords():
    request = NarrativeProjectRequest(
        project_id="project-001",
        title="雨夜来信",
        keywords=[" 悬疑 ", " 姐姐失踪 "],
        genre="悬疑",
        visual_style="电影感雨夜",
        episode_duration_seconds=45,
        episode_budget_usd=2.0,
    )

    assert request.keywords == ["悬疑", "姐姐失踪"]


def test_project_request_rejects_empty_keyword():
    with pytest.raises(ValidationError, match="空字符串"):
        NarrativeProjectRequest(
            project_id="project-001",
            title="雨夜来信",
            keywords=["悬疑", "  "],
            genre="悬疑",
            visual_style="电影感雨夜",
            episode_duration_seconds=45,
            episode_budget_usd=2.0,
        )


def test_episode_rejects_reversed_chapter_range():
    with pytest.raises(ValidationError, match="chapter_end"):
        EpisodePlan(
            project_id="project-001",
            episode_number=1,
            title="第 1 集",
            source_chapter_start=3,
            source_chapter_end=2,
            target_duration_seconds=45,
        )


def test_screenplay_rejects_duplicate_scene_ids():
    scene = ScreenplayScene(
        scene_id="scene-001",
        order=1,
        narration="林舟读到来信。",
        visual_description="雨夜室内，信封被打开。",
        duration_seconds=5,
    )

    with pytest.raises(ValidationError, match="scene_id"):
        Screenplay(scenes=[scene, scene.model_copy(update={"order": 2})])


def test_key_shot_requires_high_minimum_quality():
    with pytest.raises(ValidationError, match="min_quality_score"):
        PrioritizedShot(
            shot_id="shot-001",
            scene_id="scene-001",
            order=1,
            visual_prompt="林舟在雨夜读信的近景。",
            camera_instruction="缓慢推进",
            duration_seconds=5,
            importance=ShotImportance.KEY,
            priority_reason="揭示剧情核心线索。",
            min_quality_score=6,
        )


def test_second_episode_context_requires_previous_summary():
    with pytest.raises(ValidationError, match="previous_episode_summary"):
        ContextPack(
            episode=make_episode(number=2),
            source_chunks=[make_source_chunk()],
            style_bible="写实电影感，低饱和冷色调。",
        )


def test_valid_second_episode_context_contains_character_and_memory():
    context = ContextPack(
        episode=make_episode(number=2),
        source_chunks=[make_source_chunk()],
        characters=[
            CharacterProfile(
                character_id="character-linzhou",
                name="林舟",
                canonical_description="二十七码的青年，短黑发，左眉有浅疤。",
                immutable_traits=["短黑发", "左眉浅疤"],
                evidence_chunk_ids=["chunk-001"],
            )
        ],
        canonical_facts=["林舟的姐姐已失踪五年。"],
        previous_episode_summary=EpisodeSummary(
            episode_number=1,
            recap="林舟收到匿名来信，得知姐姐失踪案可能另有线索。",
            unresolved_loops=["匿名寄信人是谁？"],
        ),
        style_bible="写实电影感，低饱和冷色调。",
    )

    assert context.episode.episode_number == 2
    assert context.characters[0].name == "林舟"
    assert context.previous_episode_summary is not None


def test_narrative_document_rejects_blank_raw_text():
    with pytest.raises(ValidationError, match="raw_text"):
        NarrativeDocument(
            document_id="novel-001",
            project_id="project-001",
            title="雨夜来信",
            source_type="markdown",
            raw_text=" \n\t ",
        )


def test_document_chunk_rejects_invalid_character_range():
    with pytest.raises(ValidationError, match="end_char"):
        DocumentChunk(
            chunk_id="novel-001-c0000",
            document_id="novel-001",
            project_id="project-001",
            chapter_number=1,
            chunk_index=0,
            content="雨夜",
            start_char=4,
            end_char=4,
        )
