"""MySQL 知识库 Repository 的集成测试。"""

from uuid import uuid4

import pymysql

from narrative.chunking import ChunkingConfig, chunk_document
from narrative.repository import MySQLNarrativeKnowledgeRepository
from narrative.schemas import (
    EpisodePlan,
    EpisodePlanSet,
    EpisodeSummary,
    NarrativeDocument,
    NarrativeProjectProfile,
    Screenplay,
    ScreenplayCandidate,
    ScreenplayReview,
    ScreenplayScene,
)
from video.mysql_config import load_mysql_settings


def make_document() -> NarrativeDocument:
    return NarrativeDocument(
        document_id=f"novel-{uuid4()}",
        project_id=f"project-{uuid4()}",
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
    assert "narrative_project_profiles" in table_names
    assert "narrative_episode_plans" in table_names
    assert "narrative_screenplays" in table_names


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


def test_save_and_load_project_profile_from_mysql():
    settings = load_mysql_settings()
    repository = MySQLNarrativeKnowledgeRepository(settings)
    repository.setup()
    document = make_document()
    repository.save_document(
        document,
        chunk_document(document, chapter_number=1),
    )
    profile = NarrativeProjectProfile(
        project_id=document.project_id,
        manuscript_document_id=document.document_id,
        title=document.title,
        logline="匿名来信使林舟再次追查姐姐失踪案。",
        style_bible="都市悬疑、雨夜冷色调、克制电影感。",
        planned_episode_count=6,
    )

    repository.save_project_profile(profile)

    assert repository.get_project_profile(profile.project_id) == profile


def test_save_and_load_episode_plans_from_mysql():
    settings = load_mysql_settings()
    repository = MySQLNarrativeKnowledgeRepository(settings)
    repository.setup()
    document = make_document()
    chunks = chunk_document(document, chapter_number=1)
    repository.save_document(document, chunks)
    repository.save_project_profile(
        NarrativeProjectProfile(
            project_id=document.project_id,
            manuscript_document_id=document.document_id,
            title=document.title,
            logline="匿名来信使林舟再次追查姐姐失踪案。",
            style_bible="都市悬疑、雨夜冷色调、克制电影感。",
            planned_episode_count=2,
        )
    )
    plan_set = EpisodePlanSet(
        project_id=document.project_id,
        plans=[
            EpisodePlan(
                project_id=document.project_id,
                episode_number=1,
                title="第 1 集：雨夜来信",
                source_chapter_start=1,
                source_chapter_end=1,
                target_duration_seconds=45,
                episode_goal="林舟收到匿名来信。",
                closing_hook="港口仓库的门被风吹开。",
                source_chunk_ids=[chunks[0].chunk_id],
            ),
            EpisodePlan(
                project_id=document.project_id,
                episode_number=2,
                title="第 2 集：港口仓库",
                source_chapter_start=1,
                source_chapter_end=1,
                target_duration_seconds=45,
                episode_goal="林舟前往港口仓库寻找姐姐的线索。",
                closing_hook="生锈钥匙上刻着姐姐的名字。",
                source_chunk_ids=[chunks[-1].chunk_id],
            ),
        ],
    )

    repository.save_episode_plan_set(plan_set)

    assert repository.list_episode_plans(document.project_id) == plan_set.plans


def test_save_and_load_screenplay_from_mysql():
    settings = load_mysql_settings()
    repository = MySQLNarrativeKnowledgeRepository(settings)
    repository.setup()
    document = make_document()
    chunks = chunk_document(document, chapter_number=1)
    repository.save_document(document, chunks)
    repository.save_project_profile(
        NarrativeProjectProfile(
            project_id=document.project_id,
            manuscript_document_id=document.document_id,
            title=document.title,
            logline="匿名来信使林舟再次追查姐姐失踪案。",
            style_bible="都市悬疑、雨夜冷色调、克制电影感。",
            planned_episode_count=2,
        )
    )
    plan_set = EpisodePlanSet(
        project_id=document.project_id,
        plans=[
            EpisodePlan(
                project_id=document.project_id,
                episode_number=1,
                title="第 1 集：雨夜来信",
                source_chapter_start=1,
                source_chapter_end=1,
                target_duration_seconds=45,
                episode_goal="林舟收到匿名来信。",
                closing_hook="港口仓库的门被风吹开。",
                source_chunk_ids=[chunks[0].chunk_id],
            )
        ],
    )
    repository.save_episode_plan_set(plan_set)
    screenplay = Screenplay(
        project_id=document.project_id,
        episode_number=1,
        target_duration_seconds=45,
        scenes=[
            ScreenplayScene(
                scene_id="scene-001",
                order=1,
                narration="林舟收到匿名来信。",
                visual_description="雨夜邮筒旁，林舟打开湿信。",
                duration_seconds=15,
                source_chunk_ids=[chunks[0].chunk_id],
            ),
            ScreenplayScene(
                scene_id="scene-002",
                order=2,
                narration="她前往港口仓库。",
                visual_description="仓库铁门半掩，雨水打在门上。",
                duration_seconds=15,
                source_chunk_ids=[chunks[0].chunk_id],
            ),
            ScreenplayScene(
                scene_id="scene-003",
                order=3,
                narration="未知的脚步声在仓库里响起。",
                visual_description="昏黄灯光下，林舟回头看向黑暗。",
                duration_seconds=15,
                source_chunk_ids=[chunks[-1].chunk_id],
            ),
        ],
    )

    repository.save_screenplay(screenplay)

    assert repository.get_screenplay(document.project_id, 1) == screenplay


def test_mysql_candidate_approval_persists_screenplay_and_episode_summary():
    settings = load_mysql_settings()
    repository = MySQLNarrativeKnowledgeRepository(settings)
    repository.setup()
    document = make_document()
    chunks = chunk_document(document, chapter_number=1)
    repository.save_document(document, chunks)
    repository.save_project_profile(
        NarrativeProjectProfile(
            project_id=document.project_id,
            manuscript_document_id=document.document_id,
            title=document.title,
            logline="匿名来信使林舟再次追查姐姐失踪案。",
            style_bible="都市悬疑、雨夜冷色调、克制电影感。",
            planned_episode_count=2,
        )
    )
    repository.save_episode_plan_set(
        EpisodePlanSet(
            project_id=document.project_id,
            plans=[
                EpisodePlan(
                    project_id=document.project_id,
                    episode_number=1,
                    title="第 1 集：雨夜来信",
                    source_chapter_start=1,
                    source_chapter_end=1,
                    target_duration_seconds=45,
                    episode_goal="林舟收到匿名来信。",
                    closing_hook="仓库深处传来脚步声。",
                    source_chunk_ids=[chunks[0].chunk_id],
                )
            ],
        )
    )
    screenplay = Screenplay(
        project_id=document.project_id,
        episode_number=1,
        target_duration_seconds=45,
        scenes=[
            ScreenplayScene(scene_id="s1", order=1, narration="林舟收到匿名来信。", visual_description="雨夜邮筒。", duration_seconds=15, source_chunk_ids=[chunks[0].chunk_id]),
            ScreenplayScene(scene_id="s2", order=2, narration="她走向仓库。", visual_description="港口雨幕。", duration_seconds=15, source_chunk_ids=[chunks[0].chunk_id]),
            ScreenplayScene(scene_id="s3", order=3, narration="脚步声从深处传来。", visual_description="仓库暗处。", duration_seconds=15, source_chunk_ids=[chunks[0].chunk_id]),
        ],
    )
    candidate = ScreenplayCandidate(candidate_id=f"candidate-{uuid4().hex}", screenplay=screenplay)
    repository.save_screenplay_candidate(candidate)
    repository.record_screenplay_review(
        candidate.candidate_id,
        ScreenplayReview(
            passed=True,
            feedback="通过。",
            episode_summary=EpisodeSummary(
                episode_number=1,
                recap="林舟收到匿名信并前往仓库。",
                unresolved_loops=["脚步声是谁？"],
            ),
        ),
    )

    approved = repository.approve_screenplay_candidate(candidate.candidate_id)

    assert approved.status.value == "approved"
    assert repository.get_screenplay(document.project_id, 1) == screenplay
    assert repository.get_episode_summary(document.project_id, 1) is not None
