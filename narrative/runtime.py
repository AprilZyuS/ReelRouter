"""叙事生成流程的生产运行时组装入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from narrative.ark_story_writer import ArkStoryWriterClient
from narrative.context_manager import ContextManager
from narrative.embeddings import BgeM3EmbeddingProvider, EmbeddingProvider
from narrative.generation_service import (
    ManuscriptGenerator,
    NarrativeProjectGenerationService,
)
from narrative.ingestion import NarrativeIngestionService
from narrative.repository import (
    MySQLNarrativeKnowledgeRepository,
    NarrativeKnowledgeRepository,
)
from narrative.retrieval import NarrativeRetriever
from narrative.story_writer import StoryWriter
from narrative.vector_store import FaissChunkIndex
from video.mysql_config import load_mysql_settings


DEFAULT_NARRATIVE_INDEX_ROOT = Path("data") / "narrative_indexes"


@dataclass(frozen=True)
class NarrativeRuntime:
    """一次真实叙事任务所需的、已经正确连线的组件集合。"""

    repository: NarrativeKnowledgeRepository
    retriever: NarrativeRetriever
    context_manager: ContextManager
    generation_service: NarrativeProjectGenerationService


def create_narrative_runtime(
    *,
    repository: NarrativeKnowledgeRepository | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    manuscript_generator: ManuscriptGenerator | None = None,
    index_root: Path = DEFAULT_NARRATIVE_INDEX_ROOT,
    document_id_factory: Callable[[], str] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> NarrativeRuntime:
    """组装“方舟模型写小说 → MySQL 分块 → BGE-M3/FAISS 索引”的运行时。

    默认分支仅创建各组件，不会调用大模型，也不会加载 BGE-M3 权重；只有真正
    调用 ``generation_service.generate_and_ingest`` 时才会产生模型调用与向量计算。
    可选依赖注入用于单元测试，使测试不依赖 API Key、MySQL 或 GPU。
    """
    selected_repository = repository or MySQLNarrativeKnowledgeRepository(
        load_mysql_settings()
    )
    selected_repository.setup()

    selected_embedding_provider = embedding_provider or BgeM3EmbeddingProvider()
    vector_index = FaissChunkIndex(index_root, selected_embedding_provider)
    retriever = NarrativeRetriever(selected_repository, vector_index)
    context_manager = ContextManager(selected_repository, retriever)
    ingestion_service = NarrativeIngestionService(selected_repository, retriever)
    selected_generator = manuscript_generator or StoryWriter(
        ArkStoryWriterClient(),
        progress_callback=progress_callback,
    )

    return NarrativeRuntime(
        repository=selected_repository,
        retriever=retriever,
        context_manager=context_manager,
        generation_service=NarrativeProjectGenerationService(
            selected_generator,
            ingestion_service,
            selected_repository,
            document_id_factory=document_id_factory,
            progress_callback=progress_callback,
        ),
    )
