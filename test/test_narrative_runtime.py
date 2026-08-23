"""叙事生产运行时的组装测试；全程不访问模型、MySQL 或 GPU。"""

from narrative.embeddings import HashEmbeddingProvider
from narrative.repository import InMemoryNarrativeKnowledgeRepository
from narrative.runtime import create_narrative_runtime
from narrative.schemas import EpisodePlan, NarrativeProjectRequest, NovelManuscript


class FakeManuscriptGenerator:
    """只返回固定小说稿，用于确认 Runtime 的连线关系。"""

    def generate(self, request: NarrativeProjectRequest) -> NovelManuscript:
        return NovelManuscript(
            project_id=request.project_id,
            title="雨夜来信",
            logline="一封匿名来信揭开姐姐失踪案的新线索。",
            manuscript=(
                "雨下了一整夜。林舟在港口仓库收到匿名来信，"
                "信中提到失踪姐姐留下的一把钥匙。"
            )
            * 40,
            style_bible="都市悬疑，冷色调，克制的电影感镜头。",
            planned_episode_count=6,
        )


def make_request() -> NarrativeProjectRequest:
    return NarrativeProjectRequest(
        project_id="rain-letter-runtime",
        title="雨夜来信",
        keywords=["匿名来信", "姐姐失踪", "港口仓库"],
        genre="都市悬疑",
        visual_style="冷色调电影感",
        episode_duration_seconds=45,
        episode_budget_usd=2.5,
    )


def test_runtime_wires_generation_ingestion_and_retrieval(tmp_path):
    repository = InMemoryNarrativeKnowledgeRepository()
    progress: list[str] = []
    runtime = create_narrative_runtime(
        repository=repository,
        embedding_provider=HashEmbeddingProvider(),
        manuscript_generator=FakeManuscriptGenerator(),
        index_root=tmp_path,
        document_id_factory=lambda: "rain-letter-runtime-manuscript-v1",
        progress_callback=progress.append,
    )

    result = runtime.generation_service.generate_and_ingest(make_request())
    evidence = runtime.retriever.retrieve(
        result.manuscript.project_id,
        "姐姐失踪的匿名来信和港口钥匙",
        limit=2,
    )

    assert result.ingestion.index_rebuilt is True
    assert result.ingestion.chunk_count >= 1
    assert result.document.document_id == "rain-letter-runtime-manuscript-v1"
    assert repository.get_document(result.document.document_id) == result.document
    assert repository.get_project_profile(result.manuscript.project_id) == result.profile
    assert evidence
    assert all(chunk.chunk_id for chunk in evidence)

    first_chunk = repository.list_chunks(result.document.document_id)[0]
    context = runtime.context_manager.build(
        EpisodePlan(
            project_id=result.manuscript.project_id,
            episode_number=1,
            title="第 1 集：雨夜来信",
            source_chapter_start=1,
            source_chapter_end=1,
            target_duration_seconds=45,
            episode_goal="林舟确认匿名来信与姐姐失踪案有关。",
            closing_hook="港口仓库中出现新的陌生人。",
            source_chunk_ids=[first_chunk.chunk_id],
        )
    )
    assert context.style_bible == result.profile.style_bible
    assert context.source_chunks[0].chunk_id == first_chunk.chunk_id
    assert progress == [
        "阶段 1/4：正在请求 Story Writer 生成结构化小说稿。",
        "阶段 2/4：小说稿已通过数据契约校验。",
        "阶段 3/4：正在创建知识库源文档并进行分块、入库与索引构建。",
        "阶段 4/4：MySQL 文档、分块、项目 Profile 和 FAISS 索引已完成。",
    ]
