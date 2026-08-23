"""将原文导入、分块、持久化与索引重建串联为一个应用服务。"""

from dataclasses import dataclass
from typing import Protocol

from narrative.chunking import ChunkingConfig, chunk_document
from narrative.repository import NarrativeKnowledgeRepository
from narrative.schemas import NarrativeDocument


class ProjectIndexRebuilder(Protocol):
    """只暴露导入流程需要的索引重建能力，便于替换与测试。"""

    def rebuild_project_index(self, project_id: str) -> None:
        """根据 Repository 中该项目的当前全部分块重建索引。"""
        ...


class IndexRebuildRequiredError(RuntimeError):
    """原文已保存，但向量索引仍需重建时抛出的明确错误。"""

    def __init__(self, *, project_id: str, document_id: str) -> None:
        super().__init__(
            "原文已保存，但 FAISS 索引重建失败；"
            f"请重试项目 {project_id} 的索引重建（文档：{document_id}）。"
        )
        self.project_id = project_id
        self.document_id = document_id


@dataclass(frozen=True)
class IngestionResult:
    """一次成功导入的可展示结果。"""

    document_id: str
    project_id: str
    chunk_count: int
    index_rebuilt: bool


class NarrativeIngestionService:
    """负责把一篇原文安全地导入项目知识库。"""

    def __init__(
        self,
        repository: NarrativeKnowledgeRepository,
        index_rebuilder: ProjectIndexRebuilder,
        chunking_config: ChunkingConfig = ChunkingConfig(),
    ) -> None:
        self.repository = repository
        self.index_rebuilder = index_rebuilder
        self.chunking_config = chunking_config

    def ingest(
        self,
        document: NarrativeDocument,
        *,
        chapter_number: int,
    ) -> IngestionResult:
        """分块后保存原文，再以保存后的事实数据重建项目索引。"""
        chunks = chunk_document(
            document,
            chapter_number=chapter_number,
            config=self.chunking_config,
        )
        self.repository.save_document(document, chunks)

        try:
            self.index_rebuilder.rebuild_project_index(document.project_id)
        except Exception as error:
            # Repository 已是唯一事实来源；旧索引保持可用，调用方需要显式重试重建。
            raise IndexRebuildRequiredError(
                project_id=document.project_id,
                document_id=document.document_id,
            ) from error

        return IngestionResult(
            document_id=document.document_id,
            project_id=document.project_id,
            chunk_count=len(chunks),
            index_rebuilt=True,
        )

    def rebuild_project_index(self, project_id: str) -> None:
        """在发布新的项目 Profile 后重建其当前版本索引。"""
        self.index_rebuilder.rebuild_project_index(project_id)
