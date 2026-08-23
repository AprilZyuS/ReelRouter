from narrative.generation_service import NarrativeProjectGenerationService
from narrative.ingestion import IngestionResult
from narrative.schemas import (
    NarrativeDocument,
    NarrativeProjectProfile,
    NarrativeProjectRequest,
    NovelManuscript,
)


class FakeManuscriptGenerator:
    """返回固定小说稿，不调用任何真实模型。"""

    def __init__(self, manuscript: NovelManuscript) -> None:
        self.manuscript = manuscript
        self.requests: list[NarrativeProjectRequest] = []

    def generate(self, request: NarrativeProjectRequest) -> NovelManuscript:
        self.requests.append(request)
        return self.manuscript


class FakeDocumentIngestor:
    """记录导入参数，避免在本服务测试中重复测试 FAISS 实现。"""

    def __init__(self) -> None:
        self.documents: list[NarrativeDocument] = []
        self.chapter_numbers: list[int] = []

    def ingest(
        self,
        document: NarrativeDocument,
        *,
        chapter_number: int,
    ) -> IngestionResult:
        self.documents.append(document)
        self.chapter_numbers.append(chapter_number)
        return IngestionResult(
            document_id=document.document_id,
            project_id=document.project_id,
            chunk_count=3,
            index_rebuilt=True,
        )


class FakeProjectProfileStore:
    """记录 Profile 保存，验证生成服务不会只创建对象后丢弃。"""

    def __init__(self) -> None:
        self.profiles: list[NarrativeProjectProfile] = []

    def save_project_profile(self, profile: NarrativeProjectProfile) -> None:
        self.profiles.append(profile)


def make_request() -> NarrativeProjectRequest:
    return NarrativeProjectRequest(
        project_id="rain-letter",
        title="雨夜来信",
        keywords=["匿名来信", "姐姐失踪"],
        genre="都市悬疑",
        visual_style="冷色调电影感",
        episode_duration_seconds=45,
        episode_budget_usd=2.5,
    )


def make_manuscript(project_id: str = "rain-letter") -> NovelManuscript:
    return NovelManuscript(
        project_id=project_id,
        title="雨夜来信",
        logline="一封匿名来信揭开姐姐失踪案的新线索。",
        manuscript="雨下了一整夜，港口的雾遮住了旧仓库。" * 80,
        style_bible="都市悬疑，冷色调，克制叙事。",
        planned_episode_count=6,
    )


def test_generate_and_ingest_converts_manuscript_to_source_document():
    generator = FakeManuscriptGenerator(make_manuscript())
    ingestor = FakeDocumentIngestor()
    profile_store = FakeProjectProfileStore()
    service = NarrativeProjectGenerationService(
        generator,
        ingestor,
        profile_store,
        document_id_factory=lambda: "novel-rain-letter-v1",
    )

    result = service.generate_and_ingest(make_request())

    assert result.document.document_id == "novel-rain-letter-v1"
    assert result.document.project_id == "rain-letter"
    assert result.document.title == "雨夜来信"
    assert result.document.raw_text == result.manuscript.manuscript
    assert result.ingestion.chunk_count == 3
    assert ingestor.chapter_numbers == [1]
    assert result.profile.manuscript_document_id == result.document.document_id
    assert result.profile.style_bible == result.manuscript.style_bible
    assert profile_store.profiles == [result.profile]


def test_generate_and_ingest_rejects_cross_project_manuscript_before_ingestion():
    generator = FakeManuscriptGenerator(make_manuscript(project_id="wrong-project"))
    ingestor = FakeDocumentIngestor()
    profile_store = FakeProjectProfileStore()
    service = NarrativeProjectGenerationService(generator, ingestor, profile_store)

    try:
        service.generate_and_ingest(make_request())
    except ValueError as error:
        assert "project_id" in str(error)
    else:
        raise AssertionError("跨项目小说稿必须被拒绝。")

    assert ingestor.documents == []
    assert profile_store.profiles == []


def test_generate_and_ingest_uses_unique_document_ids_by_default():
    generator = FakeManuscriptGenerator(make_manuscript())
    ingestor = FakeDocumentIngestor()
    profile_store = FakeProjectProfileStore()
    service = NarrativeProjectGenerationService(generator, ingestor, profile_store)

    first = service.generate_and_ingest(make_request())
    second = service.generate_and_ingest(make_request())

    assert first.document.document_id.startswith("novel-")
    assert first.document.document_id != second.document.document_id
