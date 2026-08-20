"""MySQL 知识库 Repository 的集成测试。"""

from uuid import uuid4

import pymysql

from narrative.chunking import ChunkingConfig, chunk_document
from narrative.repository import MySQLNarrativeKnowledgeRepository
from narrative.schemas import NarrativeDocument
from video.mysql_config import load_mysql_settings


def make_document() -> NarrativeDocument:
    return NarrativeDocument(
        document_id=f"novel-{uuid4()}",
        project_id="project-001",
        title="雨夜来信",
        source_type="markdown",
        raw_text="林舟在雨夜收到匿名来信。" * 20,
    )


def test_setup_creates_narrative_tables():
    settings = load_mysql_settings()
    repository = MySQLNarrativeKnowledgeRepository(settings)
    repository.setup()

    connection = pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            table_names = {row[0] for row in cursor.fetchall()}
    finally:
        connection.close()

    assert "narrative_documents" in table_names
    assert "narrative_document_chunks" in table_names


def test_save_and_load_document_with_chunks_from_mysql():
    settings = load_mysql_settings()
    repository = MySQLNarrativeKnowledgeRepository(settings)
    repository.setup()
    document = make_document()
    chunks = chunk_document(
        document,
        chapter_number=1,
        config=ChunkingConfig(max_chars=80, overlap_chars=20),
    )

    repository.save_document(document, chunks)

    assert repository.get_document(document.document_id) == document
    assert repository.list_chunks(document.document_id) == chunks
    project_chunks = repository.list_project_chunks(document.project_id)
    saved_document_chunks = [
        chunk
        for chunk in project_chunks
        if chunk.document_id == document.document_id
    ]
    assert saved_document_chunks == chunks
