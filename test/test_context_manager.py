"""Context Manager 的确定性证据合并测试。"""

import pytest

from narrative.chunking import ChunkingConfig, chunk_document
from narrative.context_manager import ContextManager
from narrative.repository import InMemoryNarrativeKnowledgeRepository
from narrative.schemas import (
    EpisodePlan,
    EpisodePlanSet,
    EpisodeSummary,
    NarrativeDocument,
    NarrativeProjectProfile,
    SourceChunk,
)


PROJECT_ID = "rain-letter-demo"
DOCUMENT_ID = "rain-letter-demo-manuscript-v1"


class FakeRetriever:
    """只记录查询并返回固定补充证据，不加载 FAISS。"""

    def __init__(self, results: list[SourceChunk]) -> None:
        self.results = results
        self.calls: list[tuple[str, str, int]] = []

    def retrieve(
        self,
        project_id: str,
        query: str,
        *,
        limit: int = 5,
    ) -> list[SourceChunk]:
        self.calls.append((project_id, query, limit))
        return self.results


def make_episode(
    *,
    number: int = 1,
    source_chunk_ids: list[str],
) -> EpisodePlan:
    return EpisodePlan(
        project_id=PROJECT_ID,
        episode_number=number,
        title=f"第 {number} 集：雨夜来信",
        source_chapter_start=1,
        source_chapter_end=1,
        target_duration_seconds=45,
        episode_goal="林舟确认匿名来信与姐姐失踪案有关。",
        closing_hook="港口仓库深处传来金属碰撞声。",
        source_chunk_ids=source_chunk_ids,
    )


def setup_project() -> tuple[InMemoryNarrativeKnowledgeRepository, list[SourceChunk]]:
    repository = InMemoryNarrativeKnowledgeRepository()
    document = NarrativeDocument(
        document_id=DOCUMENT_ID,
        project_id=PROJECT_ID,
        title="雨夜来信",
        source_type="text",
        raw_text=(
            "雨下了一整夜。林舟收到匿名来信，信中提到失踪七年的姐姐。"
            "她循着线索来到港口仓库，在角落发现一把生锈的钥匙。"
            "钥匙背面刻着姐姐的名字，仓库深处随即传来陌生人的脚步声。"
        )
        * 4,
    )
    chunks = chunk_document(
        document,
        chapter_number=1,
        config=ChunkingConfig(max_chars=80, overlap_chars=20),
    )
    repository.save_document(document, chunks)
    repository.save_project_profile(
        NarrativeProjectProfile(
            project_id=PROJECT_ID,
            manuscript_document_id=DOCUMENT_ID,
            title="雨夜来信",
            logline="一封匿名来信重新揭开姐姐失踪案。",
            style_bible="冷色调电影感，雨夜霓虹，克制悬疑。",
            planned_episode_count=2,
        )
    )
    source_chunks = [
        SourceChunk(
            chunk_id=chunk.chunk_id,
            chapter_number=chunk.chapter_number,
            content=chunk.content,
            relevance_score=0.8,
        )
        for chunk in chunks
    ]
    return repository, source_chunks


def test_build_keeps_planned_evidence_before_rag_supplements():
    repository, chunks = setup_project()
    retriever = FakeRetriever([chunks[1], chunks[0]])
    manager = ContextManager(repository, retriever)

    context = manager.build(make_episode(source_chunk_ids=[chunks[0].chunk_id]))

    assert context.style_bible == "冷色调电影感，雨夜霓虹，克制悬疑。"
    assert context.source_chunks[0].chunk_id == chunks[0].chunk_id
    assert context.source_chunks[0].relevance_score == 1.0
    assert context.source_chunks[1].chunk_id == chunks[1].chunk_id
    assert len({chunk.chunk_id for chunk in context.source_chunks}) == len(
        context.source_chunks
    )


def test_build_queries_rag_with_episode_goal_and_closing_hook():
    repository, chunks = setup_project()
    retriever = FakeRetriever([])
    manager = ContextManager(repository, retriever)

    episode = make_episode(source_chunk_ids=[chunks[0].chunk_id])
    manager.build(episode)

    project_id, query, limit = retriever.calls[0]
    assert project_id == PROJECT_ID
    assert episode.episode_goal in query
    assert episode.closing_hook in query
    assert limit == 8


def test_build_rejects_unknown_planned_chunk_id():
    repository, _ = setup_project()
    manager = ContextManager(repository, FakeRetriever([]))

    with pytest.raises(ValueError, match="不存在的 source_chunk_ids"):
        manager.build(make_episode(source_chunk_ids=["missing-chunk"]))


def test_build_rejects_missing_project_profile():
    repository = InMemoryNarrativeKnowledgeRepository()
    manager = ContextManager(repository, FakeRetriever([]))

    with pytest.raises(LookupError, match="NarrativeProjectProfile"):
        manager.build(make_episode(source_chunk_ids=["chunk-001"]))


def test_second_episode_requires_previous_summary():
    repository, chunks = setup_project()
    manager = ContextManager(repository, FakeRetriever([]))
    episode = make_episode(number=2, source_chunk_ids=[chunks[0].chunk_id])

    with pytest.raises(ValueError, match="previous_episode_summary"):
        manager.build(episode)

    context = manager.build(
        episode,
        previous_episode_summary=EpisodeSummary(
            episode_number=1,
            recap="林舟在雨夜收到匿名来信，并前往港口仓库。",
            unresolved_loops=["仓库里的人是谁？"],
        ),
    )
    assert context.previous_episode_summary is not None


def test_persisted_two_episode_plans_build_consecutive_context_packs():
    """验证 Day 2 的交接：读取持久化计划，而不是继续使用终端临时对象。"""
    repository, chunks = setup_project()
    repository.save_episode_plan_set(
        EpisodePlanSet(
            project_id=PROJECT_ID,
            plans=[
                make_episode(number=1, source_chunk_ids=[chunks[0].chunk_id]),
                make_episode(number=2, source_chunk_ids=[chunks[-1].chunk_id]),
            ],
        )
    )
    saved_first, saved_second = repository.list_episode_plans(PROJECT_ID)
    manager = ContextManager(repository, FakeRetriever([]))

    first_context = manager.build(saved_first)
    second_context = manager.build(
        saved_second,
        previous_episode_summary=EpisodeSummary(
            episode_number=1,
            recap="林舟收到匿名来信，并在港口仓库找到钥匙。",
            unresolved_loops=["仓库深处的人是谁？"],
        ),
    )

    assert first_context.episode == saved_first
    assert first_context.source_chunks[0].chunk_id == chunks[0].chunk_id
    assert second_context.episode == saved_second
    assert second_context.previous_episode_summary is not None
    assert second_context.previous_episode_summary.episode_number == 1


def test_constructor_rejects_invalid_source_chunk_limit():
    repository, _ = setup_project()

    with pytest.raises(ValueError, match="max_source_chunks"):
        ContextManager(repository, FakeRetriever([]), max_source_chunks=9)
