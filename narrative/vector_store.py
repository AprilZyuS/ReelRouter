"""按项目构建、持久化并查询 FAISS 向量索引。"""

from collections.abc import Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import faiss
import numpy as np

from narrative.embeddings import EmbeddingProvider
from narrative.schemas import DocumentChunk


_PROJECT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_GENERATION_ID_PATTERN = re.compile(r"[a-f0-9-]{36}")


@dataclass(frozen=True)
class VectorSearchHit:
    """FAISS 返回的候选块 ID 与余弦相似度。"""

    chunk_id: str
    score: float


class FaissChunkIndex:
    """一个项目一份 FAISS 索引；MySQL 仍是原文内容的唯一事实来源。"""

    def __init__(self, index_root: Path, embedding_provider: EmbeddingProvider) -> None:
        self.index_root = index_root
        self.embedding_provider = embedding_provider

    def _project_directory(self, project_id: str) -> Path:
        if not _PROJECT_ID_PATTERN.fullmatch(project_id):
            raise ValueError("project_id 只能包含字母、数字、下划线和连字符。")
        return self.index_root / project_id

    @staticmethod
    def _atomic_write_json(path: Path, content: dict[str, object]) -> None:
        temporary_path = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
        temporary_path.write_text(
            json.dumps(content, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, path)

    def build(self, project_id: str, chunks: Sequence[DocumentChunk]) -> None:
        """为项目的全部分块建立新索引，并原子切换到新版本。"""
        # 先验证路径来源，避免后续任何逻辑使用不安全的 project_id。
        project_directory = self._project_directory(project_id)
        chunk_list = sorted(
            chunks,
            key=lambda chunk: (chunk.document_id, chunk.chunk_index),
        )
        if not chunk_list:
            raise ValueError("无法为没有分块的项目建立索引。")
        if any(chunk.project_id != project_id for chunk in chunk_list):
            raise ValueError("索引中的所有分块必须属于指定 project_id。")

        chunk_ids = [chunk.chunk_id for chunk in chunk_list]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("同一项目的 chunk_id 不能重复。")

        vectors = np.asarray(
            self.embedding_provider.embed_documents(
                [chunk.content for chunk in chunk_list]
            ),
            dtype=np.float32,
        )
        expected_shape = (len(chunk_list), self.embedding_provider.dimension)
        if vectors.shape != expected_shape:
            raise ValueError(
                f"Embedding 形状应为 {expected_shape}，实际为 {vectors.shape}。"
            )
        faiss.normalize_L2(vectors)

        index = faiss.IndexFlatIP(self.embedding_provider.dimension)
        index.add(vectors)

        generation_id = str(uuid4())
        generation_directory = project_directory / "generations" / generation_id
        generation_directory.mkdir(parents=True, exist_ok=False)
        faiss.write_index(index, str(generation_directory / "chunks.faiss"))
        self._atomic_write_json(
            generation_directory / "metadata.json",
            {
                "version": 1,
                "provider_id": self.embedding_provider.provider_id,
                "dimension": self.embedding_provider.dimension,
                "vector_count": len(chunk_ids),
                "chunk_ids": chunk_ids,
            },
        )

        # 只有索引与元数据均写完后，才更新 current 指针；异常时旧索引仍可用。
        self._atomic_write_json(
            project_directory / "current.json",
            {"generation_id": generation_id},
        )

    def _load_current_index(self, project_id: str) -> tuple[faiss.Index, list[str]]:
        project_directory = self._project_directory(project_id)
        current_path = project_directory / "current.json"
        if not current_path.exists():
            raise LookupError(f"项目 {project_id} 尚未建立向量索引。")

        current = json.loads(current_path.read_text(encoding="utf-8"))
        generation_id = current.get("generation_id")
        if not isinstance(generation_id, str) or not _GENERATION_ID_PATTERN.fullmatch(
            generation_id
        ):
            raise RuntimeError("FAISS current.json 内容无效。")

        generation_directory = project_directory / "generations" / generation_id
        metadata = json.loads(
            (generation_directory / "metadata.json").read_text(encoding="utf-8")
        )
        chunk_ids = metadata.get("chunk_ids")
        if not isinstance(chunk_ids, list) or not all(
            isinstance(chunk_id, str) for chunk_id in chunk_ids
        ):
            raise RuntimeError("FAISS 元数据中的 chunk_ids 无效。")
        if metadata.get("dimension") != self.embedding_provider.dimension:
            raise RuntimeError("当前 Embedding 维度与索引维度不一致，请重建索引。")
        if metadata.get("provider_id") != self.embedding_provider.provider_id:
            raise RuntimeError("当前 Embedding Provider 与索引不一致，请重建索引。")

        index = faiss.read_index(str(generation_directory / "chunks.faiss"))
        if index.d != self.embedding_provider.dimension or index.ntotal != len(chunk_ids):
            raise RuntimeError("FAISS 索引与元数据不一致，请重建索引。")
        return index, chunk_ids

    def search(self, project_id: str, query: str, *, limit: int = 5) -> list[VectorSearchHit]:
        """按余弦相似度搜索，并返回索引中的块 ID，不直接返回原文。"""
        if not query.strip():
            raise ValueError("query 不能为空。")
        if limit <= 0:
            raise ValueError("limit 必须大于 0。")

        index, chunk_ids = self._load_current_index(project_id)
        query_vector = np.asarray(
            self.embedding_provider.embed_queries([query]), dtype=np.float32
        )
        expected_shape = (1, self.embedding_provider.dimension)
        if query_vector.shape != expected_shape:
            raise ValueError(
                f"Embedding 形状应为 {expected_shape}，实际为 {query_vector.shape}。"
            )
        faiss.normalize_L2(query_vector)
        scores, vector_ids = index.search(query_vector, min(limit, index.ntotal))

        return [
            VectorSearchHit(chunk_id=chunk_ids[vector_id], score=float(score))
            for score, vector_id in zip(scores[0], vector_ids[0])
            if vector_id >= 0
        ]
