"""内存知识库 Repository 的单元测试。"""

import pytest

from narrative.chunking import ChunkingConfig, chunk_document
from narrative.repository import InMemoryNarrativeKnowledgeRepository
from narrative.schemas import NarrativeDocument


def make_document(raw_text: str, *, document_id: str = "novel-001") -> NarrativeDocument:
    return NarrativeDocument(
        document_id=document_id,
        project_id="project-001",
        title="雨夜来信",
        source_type="markdown",
        raw_text=raw_text,
    )


def make_chunks(document: NarrativeDocument):
    return chunk_document(
        document,
        chapter_number=1,
        config=ChunkingConfig(max_chars=20, overlap_chars=5),
    )


def test_save_and_load_document_with_chunks():
    repository = InMemoryNarrativeKnowledgeRepository()
    document = make_document("第一段。第二段。第三段。" * 8)
    chunks = make_chunks(document)

    repository.setup()
    repository.save_document(document, chunks)

    assert repository.get_document(document.document_id) == document
    assert repository.list_chunks(document.document_id) == chunks


def test_saving_same_document_replaces_old_chunks_atomically():
    repository = InMemoryNarrativeKnowledgeRepository()
    original_document = make_document("旧内容。" * 10)
    repository.save_document(original_document, make_chunks(original_document))

    updated_document = original_document.model_copy(
        update={"raw_text": "新内容。" * 4}
    )
    updated_chunks = make_chunks(updated_document)
    repository.save_document(updated_document, updated_chunks)

    assert repository.get_document(updated_document.document_id) == updated_document
    assert repository.list_chunks(updated_document.document_id) == updated_chunks


def test_save_rejects_chunk_from_another_project():
    repository = InMemoryNarrativeKnowledgeRepository()
    document = make_document("第一段。第二段。")
    invalid_chunk = make_chunks(document)[0].model_copy(
        update={"project_id": "another-project"}
    )

    with pytest.raises(ValueError, match="project_id"):
        repository.save_document(document, [invalid_chunk])


def test_unknown_document_returns_none_and_no_chunks():
    repository = InMemoryNarrativeKnowledgeRepository()

    assert repository.get_document("missing") is None
    assert repository.list_chunks("missing") == []
