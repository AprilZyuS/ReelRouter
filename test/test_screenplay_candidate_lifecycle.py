"""候选剧本、人工发布与跨集摘要的应用层验收测试。"""

import pytest

from narrative.chunking import ChunkingConfig, chunk_document
from narrative.context_manager import ContextManager
from narrative.repository import InMemoryNarrativeKnowledgeRepository
from narrative.schemas import (
    EpisodePlan,
    EpisodePlanSet,
    EpisodeSummary,
    NarrativeDocument,
    NarrativeProjectProfile,
    Screenplay,
    ScreenplayCandidate,
    ScreenplayCandidateStatus,
    ScreenplayReview,
    ScreenplayScene,
)


class EmptyRetriever:
    def retrieve(self, project_id: str, query: str, *, limit: int = 5):
        return []


def setup_repository():
    repository = InMemoryNarrativeKnowledgeRepository()
    document = NarrativeDocument(
        document_id="candidate-manuscript-v1",
        project_id="candidate-project",
        title="雨夜来信",
        source_type="text",
        raw_text=("林晓收到匿名信，决定前往港口仓库。仓库深处传来脚步声。") * 12,
    )
    chunks = chunk_document(
        document,
        chapter_number=1,
        config=ChunkingConfig(max_chars=80, overlap_chars=10),
    )
    repository.save_document(document, chunks)
    repository.save_project_profile(
        NarrativeProjectProfile(
            project_id=document.project_id,
            manuscript_document_id=document.document_id,
            title=document.title,
            logline="匿名信让林晓前往港口仓库。",
            style_bible="冷色悬疑。",
            planned_episode_count=2,
        )
    )
    plans = EpisodePlanSet(
        project_id=document.project_id,
        plans=[
            EpisodePlan(
                project_id=document.project_id,
                episode_number=1,
                title="第一集",
                source_chapter_start=1,
                source_chapter_end=1,
                target_duration_seconds=45,
                episode_goal="林晓决定前往港口仓库。",
                closing_hook="仓库深处传来脚步声。",
                source_chunk_ids=[chunks[0].chunk_id, chunks[-1].chunk_id],
            ),
            EpisodePlan(
                project_id=document.project_id,
                episode_number=2,
                title="第二集",
                source_chapter_start=1,
                source_chapter_end=1,
                target_duration_seconds=45,
                episode_goal="林晓继续调查。",
                closing_hook="新的线索浮现。",
                source_chunk_ids=[chunks[-1].chunk_id],
            ),
        ],
    )
    repository.save_episode_plan_set(plans)
    screenplay = Screenplay(
        project_id=document.project_id,
        episode_number=1,
        target_duration_seconds=45,
        scenes=[
                ScreenplayScene(scene_id="s1", order=1, narration="林晓收到匿名信。", visual_description="雨夜邮筒。", duration_seconds=15, source_chunk_ids=[chunks[0].chunk_id]),
                ScreenplayScene(scene_id="s2", order=2, narration="她走向港口仓库。", visual_description="雨中街道。", duration_seconds=15, source_chunk_ids=[chunks[0].chunk_id]),
                ScreenplayScene(scene_id="s3", order=3, narration="脚步声从深处传来。", visual_description="昏暗仓库。", duration_seconds=15, source_chunk_ids=[chunks[-1].chunk_id]),
        ],
    )
    return repository, chunks, screenplay


def passed_review() -> ScreenplayReview:
    return ScreenplayReview(
        passed=True,
        feedback="剧情停在本集悬念，证据范围正确。",
        episode_summary=EpisodeSummary(
            episode_number=1,
            recap="林晓收到匿名信并前往港口仓库，听见未知脚步声。",
            unresolved_loops=["脚步声的主人是谁？"],
        ),
    )


def test_candidate_must_be_reviewed_and_human_approved_before_publish():
    repository, _, screenplay = setup_repository()
    candidate = ScreenplayCandidate(candidate_id="candidate-1", screenplay=screenplay)
    repository.save_screenplay_candidate(candidate)

    assert repository.get_screenplay(screenplay.project_id, 1) is None
    with pytest.raises(ValueError, match="先完成 Reviewer"):
        repository.approve_screenplay_candidate(candidate.candidate_id)

    reviewed = repository.record_screenplay_review(candidate.candidate_id, passed_review())
    assert reviewed.status == ScreenplayCandidateStatus.REVIEWED
    assert repository.get_screenplay(screenplay.project_id, 1) is None

    approved = repository.approve_screenplay_candidate(candidate.candidate_id)
    assert approved.status == ScreenplayCandidateStatus.APPROVED
    assert repository.get_screenplay(screenplay.project_id, 1) == screenplay
    assert repository.get_episode_summary(screenplay.project_id, 1) == passed_review().episode_summary


def test_second_episode_context_automatically_loads_approved_summary():
    repository, _, screenplay = setup_repository()
    candidate = ScreenplayCandidate(candidate_id="candidate-2", screenplay=screenplay)
    repository.save_screenplay_candidate(candidate)
    repository.record_screenplay_review(candidate.candidate_id, passed_review())
    repository.approve_screenplay_candidate(candidate.candidate_id)

    episode_two = repository.list_episode_plans(screenplay.project_id)[1]
    context = ContextManager(repository, EmptyRetriever()).build(episode_two)

    assert context.previous_episode_summary is not None
    assert context.previous_episode_summary.episode_number == 1


def test_failed_review_cannot_be_human_approved():
    repository, _, screenplay = setup_repository()
    candidate = ScreenplayCandidate(candidate_id="candidate-3", screenplay=screenplay)
    repository.save_screenplay_candidate(candidate)
    repository.record_screenplay_review(
        candidate.candidate_id,
        ScreenplayReview(
            passed=False,
            feedback="提前揭示了后续真相。",
            violations=["越过本集范围。"],
        ),
    )

    with pytest.raises(ValueError, match="未通过"):
        repository.approve_screenplay_candidate(candidate.candidate_id)


def test_publishing_new_manuscript_version_invalidates_old_derived_assets():
    repository, _, screenplay = setup_repository()
    candidate = ScreenplayCandidate(candidate_id="candidate-version", screenplay=screenplay)
    repository.save_screenplay_candidate(candidate)
    repository.record_screenplay_review(candidate.candidate_id, passed_review())
    repository.approve_screenplay_candidate(candidate.candidate_id)

    new_document = NarrativeDocument(
        document_id="candidate-manuscript-v2",
        project_id="candidate-project",
        title="雨夜来信（重写）",
        source_type="text",
        raw_text="重写后的故事从新的雨夜线索开始。" * 30,
    )
    new_chunks = chunk_document(new_document, chapter_number=1)
    repository.save_document(new_document, new_chunks)
    repository.save_project_profile(
        NarrativeProjectProfile(
            project_id=new_document.project_id,
            manuscript_document_id=new_document.document_id,
            title=new_document.title,
            logline="新的匿名线索出现。",
            style_bible="冷色悬疑。",
            planned_episode_count=2,
            keywords=["匿名线索"],
            genre="悬疑",
            episode_duration_seconds=45,
            episode_budget_usd=2.5,
            narrative_version=2,
        )
    )

    assert repository.list_episode_plans(new_document.project_id) == []
    assert repository.get_screenplay(new_document.project_id, 1) is None
    assert repository.get_screenplay_candidate(candidate.candidate_id) is None
    assert repository.get_episode_summary(new_document.project_id, 1) is None
    assert repository.list_project_chunks(new_document.project_id) == new_chunks
