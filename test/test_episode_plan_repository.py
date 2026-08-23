"""分集计划写入知识库前的项目归属与证据引用测试。"""

import pytest

from narrative.chunking import ChunkingConfig, chunk_document
from narrative.repository import InMemoryNarrativeKnowledgeRepository
from narrative.schemas import (
    EpisodePlan,
    EpisodePlanSet,
    NarrativeDocument,
    NarrativeProjectProfile,
    Screenplay,
    ScreenplayScene,
)


PROJECT_ID = "rain-letter-plans"
DOCUMENT_ID = "rain-letter-plans-manuscript-v1"


def setup_project() -> tuple[InMemoryNarrativeKnowledgeRepository, list[str]]:
    repository = InMemoryNarrativeKnowledgeRepository()
    document = NarrativeDocument(
        document_id=DOCUMENT_ID,
        project_id=PROJECT_ID,
        title="雨夜来信",
        source_type="text",
        raw_text=(
            "林晓在雨夜收到匿名信，得知姐姐可能仍然活着。"
            "她前往港口仓库，找到铁盒和一把生锈的钥匙。"
        )
        * 8,
    )
    chunks = chunk_document(
        document,
        chapter_number=1,
        config=ChunkingConfig(max_chars=80, overlap_chars=20),
    )
    repository.save_document(document, chunks)
    repository.save_project_profile(
        NarrativeProjectProfile(
            project_id=PROJECT_ID,
            manuscript_document_id=DOCUMENT_ID,
            title=document.title,
            logline="匿名信让林晓重启姐姐失踪案的调查。",
            style_bible="雨夜霓虹、冷色调、克制悬疑。",
            planned_episode_count=2,
        )
    )
    return repository, [chunk.chunk_id for chunk in chunks]


def make_plan_set(chunk_ids: list[str], *, title_suffix: str = "") -> EpisodePlanSet:
    return EpisodePlanSet(
        project_id=PROJECT_ID,
        plans=[
            EpisodePlan(
                project_id=PROJECT_ID,
                episode_number=1,
                title=f"第 1 集：雨夜来信{title_suffix}",
                source_chapter_start=1,
                source_chapter_end=1,
                target_duration_seconds=45,
                episode_goal="林晓确认匿名信与姐姐失踪案有关。",
                closing_hook="港口仓库的铁门缓缓打开。",
                source_chunk_ids=[chunk_ids[0], chunk_ids[-1]],
            ),
            EpisodePlan(
                project_id=PROJECT_ID,
                episode_number=2,
                title=f"第 2 集：港口钥匙{title_suffix}",
                source_chapter_start=1,
                source_chapter_end=1,
                target_duration_seconds=45,
                episode_goal="林晓在仓库找到姐姐留下的关键线索。",
                closing_hook="钥匙背面刻着一个陌生名字。",
                source_chunk_ids=[chunk_ids[-1]],
            ),
        ],
    )


def test_save_and_load_episode_plans_in_order():
    repository, chunk_ids = setup_project()
    plan_set = make_plan_set(chunk_ids)

    repository.save_episode_plan_set(plan_set)

    assert repository.list_episode_plans(PROJECT_ID) == plan_set.plans


def test_save_replaces_old_plan_set_as_one_current_version():
    repository, chunk_ids = setup_project()
    repository.save_episode_plan_set(make_plan_set(chunk_ids))
    replacement = make_plan_set(chunk_ids, title_suffix="（修订版）")

    repository.save_episode_plan_set(replacement)

    saved_plans = repository.list_episode_plans(PROJECT_ID)
    assert len(saved_plans) == 2
    assert saved_plans[0].title == "第 1 集：雨夜来信（修订版）"


def test_save_rejects_source_chunk_not_in_current_manuscript():
    repository, chunk_ids = setup_project()
    invalid = make_plan_set(chunk_ids)
    invalid = invalid.model_copy(
        update={
            "plans": [
                invalid.plans[0],
                invalid.plans[1].model_copy(
                    update={"source_chunk_ids": ["other-project-c0000"]}
                ),
            ]
        }
    )

    with pytest.raises(ValueError, match="不存在的 source_chunk_ids"):
        repository.save_episode_plan_set(invalid)

    assert repository.list_episode_plans(PROJECT_ID) == []


def test_save_rejects_project_without_profile():
    repository = InMemoryNarrativeKnowledgeRepository()
    plan_set = EpisodePlanSet(
        project_id="missing-project",
        plans=[
            EpisodePlan(
                project_id="missing-project",
                episode_number=1,
                title="第 1 集",
                source_chapter_start=1,
                source_chapter_end=1,
                target_duration_seconds=45,
                episode_goal="测试。",
                closing_hook="测试悬念。",
                source_chunk_ids=["missing-c0000"],
            )
        ],
    )

    with pytest.raises(LookupError, match="NarrativeProjectProfile"):
        repository.save_episode_plan_set(plan_set)


def make_screenplay(chunk_ids: list[str], *, duration_seconds: int = 45) -> Screenplay:
    return Screenplay(
        project_id=PROJECT_ID,
        episode_number=1,
        target_duration_seconds=duration_seconds,
        scenes=[
            ScreenplayScene(
                scene_id="scene-001",
                order=1,
                narration="林晓收到匿名信。",
                visual_description="雨夜邮筒旁，林晓打开一封湿信。",
                duration_seconds=15,
                source_chunk_ids=[chunk_ids[0]],
            ),
            ScreenplayScene(
                scene_id="scene-002",
                order=2,
                narration="她赶往港口仓库。",
                visual_description="林晓穿过雨幕，仓库铁门半掩。",
                duration_seconds=15,
                source_chunk_ids=[chunk_ids[0]],
            ),
            ScreenplayScene(
                scene_id="scene-003",
                order=3,
                narration="铁盒里的照片揭开新的危险。",
                visual_description="旧铁盒中的照片在昏黄灯光下被打开。",
                duration_seconds=15,
                source_chunk_ids=[chunk_ids[-1]],
            ),
        ],
    )


def test_save_and_load_approved_screenplay():
    repository, chunk_ids = setup_project()
    repository.save_episode_plan_set(make_plan_set(chunk_ids))
    screenplay = make_screenplay(chunk_ids)

    repository.save_screenplay(screenplay)

    assert repository.get_screenplay(PROJECT_ID, 1) == screenplay


def test_save_screenplay_rejects_duration_not_matching_episode_plan():
    repository, chunk_ids = setup_project()
    repository.save_episode_plan_set(make_plan_set(chunk_ids))
    screenplay = make_screenplay(chunk_ids, duration_seconds=45)
    wrong_plan = make_plan_set(chunk_ids)
    wrong_plan = wrong_plan.model_copy(
        update={
            "plans": [
                wrong_plan.plans[0].model_copy(
                    update={"target_duration_seconds": 30}
                ),
                wrong_plan.plans[1],
            ]
        }
    )
    repository.save_episode_plan_set(wrong_plan)

    with pytest.raises(ValueError, match="目标时长"):
        repository.save_screenplay(screenplay)
