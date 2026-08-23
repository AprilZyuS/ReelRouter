"""为单集创作构造受控、可追溯的 Context Pack。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from narrative.repository import NarrativeKnowledgeRepository
from narrative.schemas import (
    CharacterProfile,
    ContextPack,
    EpisodePlan,
    EpisodeSummary,
    SourceChunk,
)


class NarrativeEvidenceRetriever(Protocol):
    """Context Manager 所需的最小语义检索能力。"""

    def retrieve(
        self,
        project_id: str,
        query: str,
        *,
        limit: int = 5,
    ) -> list[SourceChunk]:
        """返回按语义相关度排序的项目原文证据。"""
        ...


class ContextManager:
    """合并计划硬证据、RAG 补充证据和项目长期状态。

    EpisodePlan 的 source_chunk_ids 是 Story Planner 已确认的硬约束，必须原样
    出现在输出中；FAISS 结果只能补充，不能替代这些证据。
    """

    def __init__(
        self,
        repository: NarrativeKnowledgeRepository,
        retriever: NarrativeEvidenceRetriever,
        *,
        max_source_chunks: int = 8,
    ) -> None:
        if not 1 <= max_source_chunks <= 8:
            raise ValueError("max_source_chunks 必须在 1 到 8 之间。")
        self.repository = repository
        self.retriever = retriever
        self.max_source_chunks = max_source_chunks

    def build(
        self,
        episode: EpisodePlan,
        *,
        characters: Sequence[CharacterProfile] = (),
        canonical_facts: Sequence[str] = (),
        previous_episode_summary: EpisodeSummary | None = None,
    ) -> ContextPack:
        """构造一集的受控上下文，不生成任何模型文本。"""
        profile = self.repository.get_project_profile(episode.project_id)
        if profile is None:
            raise LookupError(f"项目 {episode.project_id} 不存在 NarrativeProjectProfile。")

        # 跨集长期记忆只能来自已批准上一集。调用方不再需要把临时对象一路
        # 手工传到第 2 集，进程重启后也会从 Repository 恢复。
        if previous_episode_summary is None and episode.episode_number > 1:
            previous_episode_summary = self.repository.get_episode_summary(
                episode.project_id,
                episode.episode_number - 1,
            )

        manuscript_chunks = self.repository.list_chunks(
            profile.manuscript_document_id
        )
        chunks_by_id = {chunk.chunk_id: chunk for chunk in manuscript_chunks}
        missing_chunk_ids = [
            chunk_id
            for chunk_id in episode.source_chunk_ids
            if chunk_id not in chunks_by_id
        ]
        if missing_chunk_ids:
            raise ValueError(
                "EpisodePlan 引用了当前小说稿中不存在的 source_chunk_ids："
                + ", ".join(missing_chunk_ids)
            )

        # 计划显式选择的块优先级最高；relevance_score=1 表示“规划证据”，
        # 并非 FAISS 的相似度分数。
        source_chunks = [
            SourceChunk(
                chunk_id=chunk_id,
                chapter_number=chunks_by_id[chunk_id].chapter_number,
                content=chunks_by_id[chunk_id].content,
                relevance_score=1.0,
            )
            for chunk_id in episode.source_chunk_ids
        ]

        retrieval_query = self._build_retrieval_query(episode)
        retrieved_chunks = self.retriever.retrieve(
            episode.project_id,
            retrieval_query,
            limit=self.max_source_chunks,
        )
        known_chunk_ids = {chunk.chunk_id for chunk in source_chunks}
        for chunk in retrieved_chunks:
            if chunk.chunk_id in known_chunk_ids:
                continue
            source_chunks.append(chunk)
            known_chunk_ids.add(chunk.chunk_id)
            if len(source_chunks) == self.max_source_chunks:
                break

        return ContextPack(
            episode=episode,
            source_chunks=source_chunks,
            characters=list(characters),
            canonical_facts=list(canonical_facts),
            previous_episode_summary=previous_episode_summary,
            style_bible=profile.style_bible,
        )

    @staticmethod
    def _build_retrieval_query(episode: EpisodePlan) -> str:
        """用本集目标与悬念查询补充证据，避免把完整小说塞进 Prompt。"""
        return "\n".join(
            [episode.title, episode.episode_goal, episode.closing_hook]
        )
