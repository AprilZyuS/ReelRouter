"""叙事原文导入服务的单元测试。"""

import pytest

from narrative.chunking import ChunkingConfig
from narrative.embeddings import HashEmbeddingProvider
from narrative.ingestion import (
    IndexRebuildRequiredError,
    NarrativeIngestionService,
)
from narrative.repository import InMemoryNarrativeKnowledgeRepository
from narrative.retrieval import NarrativeRetriever
from narrative.schemas import NarrativeDocument
from narrative.vector_store import FaissChunkIndex


def make_document(raw_text: str) -> NarrativeDocument:
    return NarrativeDocument(
        document_id="novel-001",
        project_id="project-001",
        title="雨夜来信",
        source_type="markdown",
        raw_text=raw_text,
    )


def make_service(tmp_path):
    repository = InMemoryNarrativeKnowledgeRepository()
    retriever = NarrativeRetriever(
        repository,
        FaissChunkIndex(tmp_path, HashEmbeddingProvider()),
    )
    service = NarrativeIngestionService(
        repository,
        retriever,
        ChunkingConfig(max_chars=30, overlap_chars=8),
    )
    return service, repository, retriever


def test_ingest_saves_chunks_and_rebuilds_project_index(tmp_path):
    service, repository, retriever = make_service(tmp_path)
    document = make_document("雨夜匿名来信提到失踪五年的姐姐。" * 4)

    result = service.ingest(document, chapter_number=1)

    assert result.document_id == document.document_id
    assert result.chunk_count == len(repository.list_chunks(document.document_id))
    assert result.index_rebuilt is True
    assert retriever.retrieve(document.project_id, "姐姐失踪的匿名来信", limit=1)


def test_reingest_replaces_document_chunks_and_rebuilds_index(tmp_path):
    service, repository, retriever = make_service(tmp_path)
    service.ingest(make_document("旧剧情：港口出现一把钥匙。" * 4), chapter_number=1)
    updated_document = make_document("新剧情：雨夜来信揭示姐姐的线索。" * 4)

    service.ingest(updated_document, chapter_number=1)
    results = retriever.retrieve(
        updated_document.project_id,
        "姐姐线索和雨夜来信",
        limit=1,
    )

    assert "姐姐" in results[0].content
    assert all("港口" not in chunk.content for chunk in repository.list_chunks("novel-001"))


def test_invalid_chapter_does_not_persist_document(tmp_path):
    service, repository, _ = make_service(tmp_path)
    document = make_document("雨夜来信。")

    with pytest.raises(ValueError, match="chapter_number"):
        service.ingest(document, chapter_number=0)

    assert repository.get_document(document.document_id) is None


class FailingIndexRebuilder:
    def rebuild_project_index(self, project_id: str) -> None:
        raise OSError(f"无法写入 {project_id} 的索引文件。")


def test_index_failure_keeps_document_and_requests_retry():
    repository = InMemoryNarrativeKnowledgeRepository()
    service = NarrativeIngestionService(
        repository,
        FailingIndexRebuilder(),
    )
    document = make_document("雨夜来信。")

    with pytest.raises(IndexRebuildRequiredError, match="FAISS"):
        service.ingest(document, chapter_number=1)

    assert repository.get_document(document.document_id) == document
    assert repository.list_chunks(document.document_id)
