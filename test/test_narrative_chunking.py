"""原文分块器的单元测试。"""

import pytest

from narrative.chunking import ChunkingConfig, chunk_document
from narrative.schemas import NarrativeDocument


def make_document(raw_text: str) -> NarrativeDocument:
    return NarrativeDocument(
        document_id="novel-001",
        project_id="project-001",
        title="雨夜来信",
        source_type="markdown",
        raw_text=raw_text,
    )


def test_short_text_creates_one_chunk():
    document = make_document("林舟在雨夜收到一封信。")

    chunks = chunk_document(document, chapter_number=1)

    assert len(chunks) == 1
    assert chunks[0].content == document.raw_text
    assert chunks[0].chunk_id == "novel-001-c0000"


def test_long_text_creates_bounded_chunks_with_exact_source_positions():
    raw_text = "甲" * 13 + "。" + "乙" * 13 + "。" + "丙" * 13 + "。"
    document = make_document(raw_text)
    config = ChunkingConfig(max_chars=20, overlap_chars=5)

    chunks = chunk_document(document, chapter_number=2, config=config)

    assert len(chunks) >= 2
    assert all(len(chunk.content) <= config.max_chars for chunk in chunks)
    assert all(
        chunk.content == raw_text[chunk.start_char : chunk.end_char]
        for chunk in chunks
    )
    assert all(chunk.chapter_number == 2 for chunk in chunks)


def test_adjacent_chunks_keep_configured_overlap():
    document = make_document("甲" * 55)
    config = ChunkingConfig(max_chars=20, overlap_chars=6)

    chunks = chunk_document(document, chapter_number=1, config=config)

    for previous, current in zip(chunks, chunks[1:]):
        assert previous.end_char - current.start_char == config.overlap_chars
        assert previous.content[-config.overlap_chars :] == current.content[: config.overlap_chars]


def test_chunk_ids_and_indexes_are_continuous_and_deterministic():
    document = make_document("第一段。\n\n第二段。\n\n第三段。" * 10)
    config = ChunkingConfig(max_chars=30, overlap_chars=8)

    first_result = chunk_document(document, chapter_number=1, config=config)
    second_result = chunk_document(document, chapter_number=1, config=config)

    assert [chunk.chunk_index for chunk in first_result] == list(range(len(first_result)))
    assert [chunk.chunk_id for chunk in first_result] == [
        f"novel-001-c{index:04d}" for index in range(len(first_result))
    ]
    assert first_result == second_result


@pytest.mark.parametrize(
    ("max_chars", "overlap_chars"),
    [(0, 0), (10, -1), (10, 10)],
)
def test_chunking_config_rejects_invalid_values(max_chars: int, overlap_chars: int):
    with pytest.raises(ValueError):
        ChunkingConfig(max_chars=max_chars, overlap_chars=overlap_chars)


def test_chunk_document_rejects_invalid_chapter_number():
    with pytest.raises(ValueError, match="chapter_number"):
        chunk_document(make_document("林舟收到来信。"), chapter_number=0)
