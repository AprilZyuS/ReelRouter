"""连接 MySQL 原文库与 FAISS 索引的语义检索服务。"""

from narrative.repository import NarrativeKnowledgeRepository
from narrative.schemas import SourceChunk
from narrative.vector_store import FaissChunkIndex


class NarrativeRetriever:
    """重建项目索引，并将向量命中结果还原为可引用的原文证据。"""

    def __init__(
        self,
        repository: NarrativeKnowledgeRepository,
        vector_index: FaissChunkIndex,
    ) -> None:
        self.repository = repository
        self.vector_index = vector_index

    def rebuild_project_index(self, project_id: str) -> None:
        """从 Repository 读取项目全部块，构建该项目的新索引版本。"""
        self.vector_index.build(
            project_id,
            self.repository.list_project_chunks(project_id),
        )

    def retrieve(
        self,
        project_id: str,
        query: str,
        *,
        limit: int = 5,
    ) -> list[SourceChunk]:
        """检索相关块，并输出 Story Writer 可直接引用的 SourceChunk。"""
        hits = self.vector_index.search(project_id, query, limit=limit)
        chunks_by_id = {
            chunk.chunk_id: chunk
            for chunk in self.repository.list_project_chunks(project_id)
        }

        results: list[SourceChunk] = []
        for hit in hits:
            chunk = chunks_by_id.get(hit.chunk_id)
            if chunk is None:
                raise RuntimeError("FAISS 索引包含 Repository 中不存在的 chunk_id，请重建索引。")
            # 余弦相似度范围是 [-1, 1]；SourceChunk 契约要求 [0, 1]。
            relevance_score = max(0.0, min(1.0, (hit.score + 1.0) / 2.0))
            results.append(
                SourceChunk(
                    chunk_id=chunk.chunk_id,
                    chapter_number=chunk.chapter_number,
                    content=chunk.content,
                    relevance_score=relevance_score,
                )
            )
        return results
