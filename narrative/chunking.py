"""将原始长文本稳定切分为带来源位置的知识库分块。"""

from dataclasses import dataclass

from narrative.schemas import DocumentChunk, NarrativeDocument


@dataclass(frozen=True)
class ChunkingConfig:
    """分块策略。字符数只用于 v1 的确定性切分，不等同于模型 Token 数。"""

    max_chars: int = 800
    overlap_chars: int = 120

    def __post_init__(self) -> None:
        if self.max_chars <= 0:
            raise ValueError("max_chars 必须大于 0。")
        if self.overlap_chars < 0:
            raise ValueError("overlap_chars 不能小于 0。")
        if self.overlap_chars >= self.max_chars:
            raise ValueError("overlap_chars 必须小于 max_chars。")


_PREFERRED_BOUNDARIES = "\n。！？.!?"


def _choose_chunk_end(text: str, *, start: int, config: ChunkingConfig) -> int:
    """在长度上限内尽量寻找自然边界；找不到时使用硬切。"""
    hard_end = min(start + config.max_chars, len(text))
    if hard_end == len(text):
        return hard_end

    # 边界若过早，会使下一块从与本块相同的位置重新开始，造成死循环。
    minimum_end = start + max(config.max_chars // 2, config.overlap_chars + 1)
    latest_boundary = -1
    for boundary in _PREFERRED_BOUNDARIES:
        latest_boundary = max(latest_boundary, text.rfind(boundary, start, hard_end))

    if latest_boundary >= minimum_end - 1:
        # 让标点或换行归属当前块，下一块从其后的重叠位置开始。
        return latest_boundary + 1

    return hard_end

def chunk_document(
    document: NarrativeDocument,
    *,
    chapter_number: int,
    config: ChunkingConfig = ChunkingConfig(),
) -> list[DocumentChunk]:
    """按固定配置切分文档，输出可从原文精确定位的分块列表。"""
    if chapter_number < 1:
        raise ValueError("chapter_number 必须大于或等于 1。")

    text = document.raw_text
    chunks: list[DocumentChunk] = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = _choose_chunk_end(text, start=start, config=config)
        content = text[start:end]

        chunks.append(
            DocumentChunk(
                chunk_id=f"{document.document_id}-c{chunk_index:04d}",
                document_id=document.document_id,
                project_id=document.project_id,
                chapter_number=chapter_number,
                chunk_index=chunk_index,
                content=content,
                start_char=start,
                end_char=end,
            )
        )

        if end == len(text):
            break

        # 下一块回退 overlap_chars，保留跨块语义；配置校验保证 start 会前进。
        start = end - config.overlap_chars
        chunk_index += 1

    return chunks
