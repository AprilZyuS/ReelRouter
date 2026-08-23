"""把小说生成与知识库导入串联为可替换、可测试的应用服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol
from uuid import uuid4

from narrative.ingestion import IngestionResult
from narrative.schemas import (
    NarrativeDocument,
    NarrativeProjectProfile,
    NarrativeProjectRequest,
    NovelManuscript,
)


class ManuscriptGenerator(Protocol):
    """只声明本服务真正需要的 Story Writer 能力。"""

    def generate(self, request: NarrativeProjectRequest) -> NovelManuscript:
        """依据项目创作要求生成一份小说稿。"""
        ...


class NarrativeDocumentIngestor(Protocol):
    """只声明小说稿入库所需的最小能力。"""

    def ingest(
        self,
        document: NarrativeDocument,
        *,
        chapter_number: int,
    ) -> IngestionResult:
        """保存文档、分块并重建项目向量索引。"""
        ...


class NarrativeProjectProfileStore(Protocol):
    """只声明生成服务保存项目长期状态所需的最小能力。"""

    def save_project_profile(self, profile: NarrativeProjectProfile) -> None:
        """保存一份仅在完整入库后才有效的项目 Profile。"""
        ...


@dataclass(frozen=True)
class GeneratedNarrativeProject:
    """一次生成并导入完成后，交给后续 Context Manager 的明确结果。"""

    manuscript: NovelManuscript
    document: NarrativeDocument
    ingestion: IngestionResult
    profile: NarrativeProjectProfile


class NarrativeProjectGenerationService:
    """负责将模型生成的小说安全转化为项目知识库源文档。"""

    def __init__(
        self,
        generator: ManuscriptGenerator,
        ingestor: NarrativeDocumentIngestor,
        profile_store: NarrativeProjectProfileStore,
        document_id_factory: Callable[[], str] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.generator = generator
        self.ingestor = ingestor
        self.profile_store = profile_store
        self.document_id_factory = document_id_factory
        self.progress_callback = progress_callback

    def generate_and_ingest(
        self,
        request: NarrativeProjectRequest,
    ) -> GeneratedNarrativeProject:
        """生成小说，再将它作为项目唯一事实来源导入知识库。"""
        self._report("阶段 1/4：正在请求 Story Writer 生成结构化小说稿。")
        manuscript = self.generator.generate(request)
        self._report("阶段 2/4：小说稿已通过数据契约校验。")

        # 即使接入的生成器不是 StoryWriter，也不允许其把小说写入另一个项目。
        if manuscript.project_id != request.project_id:
            raise ValueError("生成的小说稿 project_id 与请求项目不一致。")

        self._report("阶段 3/4：正在创建知识库源文档并进行分块、入库与索引构建。")
        profile_reader = getattr(self.profile_store, "get_project_profile", None)
        previous_profile = (
            profile_reader(request.project_id) if callable(profile_reader) else None
        )
        narrative_version = (
            previous_profile.narrative_version + 1
            if previous_profile is not None
            else 1
        )
        document_id = (
            self.document_id_factory()
            if self.document_id_factory is not None
            else self._default_document_id(request.project_id, narrative_version)
        )
        document = NarrativeDocument(
            document_id=document_id,
            project_id=request.project_id,
            title=manuscript.title,
            source_type="text",
            raw_text=manuscript.manuscript,
        )

        profile = NarrativeProjectProfile(
            project_id=manuscript.project_id,
            manuscript_document_id=document.document_id,
            title=manuscript.title,
            logline=manuscript.logline,
            style_bible=manuscript.style_bible,
            planned_episode_count=manuscript.planned_episode_count,
            keywords=request.keywords,
            genre=request.genre,
            episode_duration_seconds=request.episode_duration_seconds,
            episode_budget_usd=request.episode_budget_usd,
            enable_assembly=request.enable_assembly,
            narrative_version=narrative_version,
        )

        ingestion = self.ingestor.ingest(document, chapter_number=1)
        # Profile 必须在文档和项目索引均成功后再写入，避免后续 Agent 读取到
        # 指向不可检索原文的“半完成项目”。
        self.profile_store.save_project_profile(profile)
        # 新版本发布后，Repository 的“当前项目分块”只会返回新稿。首次导入
        # 已在 ingest 中建索引；重生成时再建一次，确保 current 指针不会仍指向
        # 上一版 Profile 的原文。
        if previous_profile is not None:
            rebuild = getattr(self.ingestor, "rebuild_project_index", None)
            if not callable(rebuild):
                raise RuntimeError("重生成项目需要 Ingestor 支持重建当前版本 FAISS 索引。")
            rebuild(request.project_id)
        self._report("阶段 4/4：MySQL 文档、分块、项目 Profile 和 FAISS 索引已完成。")

        return GeneratedNarrativeProject(
            manuscript=manuscript,
            document=document,
            ingestion=ingestion,
            profile=profile,
        )

    @staticmethod
    def _default_document_id(project_id: str, narrative_version: int) -> str:
        """生成稳定可读的版本化文档 ID，旧稿保留但不再作为当前事实来源。"""
        return f"novel-{project_id}-v{narrative_version}-{uuid4().hex[:8]}"

    def _report(self, message: str) -> None:
        """向 CLI 或 API 观察层报告阶段进度；核心业务本身不依赖控制台。"""
        if self.progress_callback is not None:
            self.progress_callback(message)
