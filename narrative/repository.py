"""长文本与原文分块的持久化接口及实现。"""

from collections.abc import Sequence
from typing import Protocol

import pymysql
from pymysql.cursors import DictCursor

from narrative.schemas import DocumentChunk, NarrativeDocument


class MySQLConnectionSettings(Protocol):
    """叙事模块需要的最小 MySQL 连接配置，避免依赖 video 领域。"""

    host: str
    port: int
    database: str
    user: str
    password: str


class NarrativeKnowledgeRepository(Protocol):
    """文档与分块的存取契约；上层不关心具体存储介质。"""

    def setup(self) -> None:
        """初始化存储所需的表或索引；重复调用必须安全。"""
        ...

    def save_document(
        self,
        document: NarrativeDocument,
        chunks: Sequence[DocumentChunk],
    ) -> None:
        """原子保存一篇原文及其完整分块集合。"""
        ...

    def get_document(self, document_id: str) -> NarrativeDocument | None:
        """按 ID 读取原文；不存在时返回 None。"""
        ...

    def list_chunks(self, document_id: str) -> list[DocumentChunk]:
        """按原文顺序读取全部分块。"""
        ...

    def list_project_chunks(self, project_id: str) -> list[DocumentChunk]:
        """按稳定顺序读取一个项目的全部分块，用于重建项目向量索引。"""
        ...


def _validate_document_chunks(
    document: NarrativeDocument,
    chunks: Sequence[DocumentChunk],
) -> list[DocumentChunk]:
    """在写入前验证分块可完整、精确地回指给定原文。"""
    chunk_list = list(chunks)
    if not chunk_list:
        raise ValueError("保存文档时至少需要一个分块。")

    expected_indexes = list(range(len(chunk_list)))
    actual_indexes = [chunk.chunk_index for chunk in chunk_list]
    if actual_indexes != expected_indexes:
        raise ValueError("chunk_index 必须从 0 开始连续递增。")

    for chunk in chunk_list:
        if chunk.document_id != document.document_id:
            raise ValueError("分块的 document_id 必须与文档一致。")
        if chunk.project_id != document.project_id:
            raise ValueError("分块的 project_id 必须与文档一致。")
        if chunk.content != document.raw_text[chunk.start_char : chunk.end_char]:
            raise ValueError("分块 content 必须精确对应原文的字符位置区间。")

    if chunk_list[0].start_char != 0:
        raise ValueError("第一个分块必须从原文开头开始。")
    if chunk_list[-1].end_char != len(document.raw_text):
        raise ValueError("最后一个分块必须覆盖到原文结尾。")

    for previous, current in zip(chunk_list, chunk_list[1:]):
        if current.start_char > previous.end_char:
            raise ValueError("相邻分块之间不能遗漏原文内容。")
        if current.end_char <= previous.end_char:
            raise ValueError("相邻分块的结束位置必须持续前进。")

    return chunk_list


class InMemoryNarrativeKnowledgeRepository:
    """用于单元测试与本地开发的内存知识库实现。"""

    def __init__(self) -> None:
        self._documents: dict[str, NarrativeDocument] = {}
        self._chunks: dict[str, list[DocumentChunk]] = {}

    def setup(self) -> None:
        """内存实现无需建表，保留该方法以遵守统一接口。"""

    def save_document(
        self,
        document: NarrativeDocument,
        chunks: Sequence[DocumentChunk],
    ) -> None:
        validated_chunks = _validate_document_chunks(document, chunks)
        self._documents[document.document_id] = document
        self._chunks[document.document_id] = validated_chunks

    def get_document(self, document_id: str) -> NarrativeDocument | None:
        return self._documents.get(document_id)

    def list_chunks(self, document_id: str) -> list[DocumentChunk]:
        return list(self._chunks.get(document_id, []))

    def list_project_chunks(self, project_id: str) -> list[DocumentChunk]:
        chunks = [
            chunk
            for document_id, document in self._documents.items()
            if document.project_id == project_id
            for chunk in self._chunks[document_id]
        ]
        return sorted(chunks, key=lambda chunk: (chunk.document_id, chunk.chunk_index))


class MySQLNarrativeKnowledgeRepository:
    """使用 MySQL 保存原文及可回溯的知识库分块。"""

    def __init__(self, settings: MySQLConnectionSettings) -> None:
        self.settings = settings

    def _connect(self):
        return pymysql.connect(
            host=self.settings.host,
            port=self.settings.port,
            user=self.settings.user,
            password=self.settings.password,
            database=self.settings.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )

    def setup(self) -> None:
        """创建叙事文档表与分块表；允许重复初始化。"""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_documents (
                        document_id VARCHAR(64) PRIMARY KEY,
                        project_id VARCHAR(64) NOT NULL,
                        title VARCHAR(200) NOT NULL,
                        source_type VARCHAR(16) NOT NULL,
                        raw_text LONGTEXT NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_narrative_documents_project (project_id)
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_document_chunks (
                        chunk_id VARCHAR(80) PRIMARY KEY,
                        document_id VARCHAR(64) NOT NULL,
                        project_id VARCHAR(64) NOT NULL,
                        chapter_number INT UNSIGNED NOT NULL,
                        chunk_index INT UNSIGNED NOT NULL,
                        content MEDIUMTEXT NOT NULL,
                        start_char INT UNSIGNED NOT NULL,
                        end_char INT UNSIGNED NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT fk_narrative_chunks_document
                            FOREIGN KEY (document_id)
                            REFERENCES narrative_documents(document_id)
                            ON DELETE CASCADE,
                        UNIQUE KEY uq_narrative_chunks_document_index
                            (document_id, chunk_index),
                        INDEX idx_narrative_chunks_project_document
                            (project_id, document_id, chunk_index)
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_document(
        self,
        document: NarrativeDocument,
        chunks: Sequence[DocumentChunk],
    ) -> None:
        """事务内更新原文，并以新分块集合完整替换旧集合。"""
        validated_chunks = _validate_document_chunks(document, chunks)
        connection = self._connect()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO narrative_documents (
                        document_id, project_id, title, source_type, raw_text
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        project_id = VALUES(project_id),
                        title = VALUES(title),
                        source_type = VALUES(source_type),
                        raw_text = VALUES(raw_text)
                    """,
                    (
                        document.document_id,
                        document.project_id,
                        document.title,
                        document.source_type,
                        document.raw_text,
                    ),
                )
                cursor.execute(
                    "DELETE FROM narrative_document_chunks WHERE document_id = %s",
                    (document.document_id,),
                )
                cursor.executemany(
                    """
                    INSERT INTO narrative_document_chunks (
                        chunk_id,
                        document_id,
                        project_id,
                        chapter_number,
                        chunk_index,
                        content,
                        start_char,
                        end_char
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            chunk.chunk_id,
                            chunk.document_id,
                            chunk.project_id,
                            chunk.chapter_number,
                            chunk.chunk_index,
                            chunk.content,
                            chunk.start_char,
                            chunk.end_char,
                        )
                        for chunk in validated_chunks
                    ],
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_document(self, document_id: str) -> NarrativeDocument | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT document_id, project_id, title, source_type, raw_text
                    FROM narrative_documents
                    WHERE document_id = %s
                    """,
                    (document_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()

        if row is None:
            return None
        return NarrativeDocument(**row)

    def list_chunks(self, document_id: str) -> list[DocumentChunk]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        chunk_id,
                        document_id,
                        project_id,
                        chapter_number,
                        chunk_index,
                        content,
                        start_char,
                        end_char
                    FROM narrative_document_chunks
                    WHERE document_id = %s
                    ORDER BY chunk_index ASC
                    """,
                    (document_id,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        return [DocumentChunk(**row) for row in rows]

    def list_project_chunks(self, project_id: str) -> list[DocumentChunk]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        chunk_id,
                        document_id,
                        project_id,
                        chapter_number,
                        chunk_index,
                        content,
                        start_char,
                        end_char
                    FROM narrative_document_chunks
                    WHERE project_id = %s
                    ORDER BY document_id ASC, chunk_index ASC
                    """,
                    (project_id,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        return [DocumentChunk(**row) for row in rows]
