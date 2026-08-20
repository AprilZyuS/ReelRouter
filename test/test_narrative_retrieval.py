"""FAISS 索引与叙事检索服务的测试。"""

from narrative.chunking import ChunkingConfig, chunk_document
from narrative.embeddings import HashEmbeddingProvider
from narrative.repository import InMemoryNarrativeKnowledgeRepository
from narrative.retrieval import NarrativeRetriever
from narrative.schemas import NarrativeDocument
from narrative.vector_store import FaissChunkIndex


def make_document(
    *,
    document_id: str,
    raw_text: str,
    project_id: str = "project-001",
) -> NarrativeDocument:
    return NarrativeDocument(
        document_id=document_id,
        project_id=project_id,
        title=document_id,
        source_type="text",
        raw_text=raw_text,
    )


def save_document(
    repository: InMemoryNarrativeKnowledgeRepository,
    document: NarrativeDocument,
) -> None:
    chunks = chunk_document(
        document,
        chapter_number=1,
        config=ChunkingConfig(max_chars=120, overlap_chars=20),
    )
    repository.save_document(document, chunks)


def test_faiss_index_persists_and_returns_exact_text_as_top_hit(tmp_path):
    document = make_document(
        document_id="novel-001",
        raw_text="雨夜的匿名信揭开姐姐失踪案的新线索。",
    )
    chunks = chunk_document(document, chapter_number=1)
    index = FaissChunkIndex(tmp_path, HashEmbeddingProvider())

    index.build(document.project_id, chunks)

    # 使用新的 Index 对象读取磁盘，证明检索没有依赖内存中的临时状态。
    loaded_index = FaissChunkIndex(tmp_path, HashEmbeddingProvider())
    hits = loaded_index.search(document.project_id, document.raw_text, limit=1)

    assert hits[0].chunk_id == chunks[0].chunk_id
    assert hits[0].score > 0.99


def test_retriever_returns_source_chunks_from_project_knowledge_base(tmp_path):
    repository = InMemoryNarrativeKnowledgeRepository()
    save_document(
        repository,
        make_document(
            document_id="rain-letter",
            raw_text="雨夜的匿名来信提到失踪五年的姐姐。",
        ),
    )
    save_document(
        repository,
        make_document(
            document_id="harbor-chase",
            raw_text="港口仓库的追逐让林舟发现了一把旧钥匙。",
        ),
    )
    retriever = NarrativeRetriever(
        repository,
        FaissChunkIndex(tmp_path, HashEmbeddingProvider()),
    )

    retriever.rebuild_project_index("project-001")
    results = retriever.retrieve(
        "project-001",
        "匿名来信和姐姐失踪的线索",
        limit=1,
    )

    assert results[0].chunk_id.startswith("rain-letter")
    assert "姐姐" in results[0].content
    assert 0 <= results[0].relevance_score <= 1


def test_project_indexes_are_isolated(tmp_path):
    index = FaissChunkIndex(tmp_path, HashEmbeddingProvider())
    first_document = make_document(
        document_id="first",
        project_id="project-one",
        raw_text="第一项目只讨论雨夜来信。",
    )
    second_document = make_document(
        document_id="second",
        project_id="project-two",
        raw_text="第二项目只讨论太空远航。",
    )
    index.build("project-one", chunk_document(first_document, chapter_number=1))
    index.build("project-two", chunk_document(second_document, chapter_number=1))

    hits = index.search("project-two", "太空远航", limit=1)

    assert hits[0].chunk_id.startswith("second")


def test_search_rejects_empty_query_and_unsafe_project_id(tmp_path):
    index = FaissChunkIndex(tmp_path, HashEmbeddingProvider())

    try:
        index.search("project-001", "   ")
    except ValueError as error:
        assert "query" in str(error)
    else:
        raise AssertionError("空查询必须被拒绝。")

    try:
        index.build("../unsafe", [])
    except ValueError as error:
        assert "project_id" in str(error)
    else:
        raise AssertionError("不安全 project_id 必须被拒绝。")


def test_search_rejects_index_built_by_another_embedding_provider(tmp_path):
    document = make_document(
        document_id="novel-001",
        raw_text="雨夜来信。",
    )
    chunks = chunk_document(document, chapter_number=1)
    FaissChunkIndex(tmp_path, HashEmbeddingProvider(dimension=128)).build(
        document.project_id,
        chunks,
    )

    class AlternativeHashEmbeddingProvider(HashEmbeddingProvider):
        @property
        def provider_id(self) -> str:
            return "another-provider-with-the-same-dimension"

    incompatible_index = FaissChunkIndex(
        tmp_path,
        AlternativeHashEmbeddingProvider(dimension=128),
    )

    try:
        incompatible_index.search(document.project_id, "雨夜")
    except RuntimeError as error:
        assert "Provider" in str(error)
    else:
        raise AssertionError("不同 Provider 创建的索引必须被拒绝。")
