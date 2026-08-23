"""分集计划数据契约测试。"""

import pytest
from pydantic import ValidationError

from narrative.schemas import EpisodePlan, EpisodePlanSet


PROJECT_ID = "rain-letter-demo-001"
CHUNK_1 = "rain-letter-demo-001-manuscript-v1-c0000"
CHUNK_2 = "rain-letter-demo-001-manuscript-v1-c0001"


def make_episode_plan(
    *,
    episode_number: int = 1,
    project_id: str = PROJECT_ID,
    source_chunk_ids: list[str] | None = None,
    **overrides: object,
) -> EpisodePlan:
    data: dict[str, object] = {
        "project_id": project_id,
        "episode_number": episode_number,
        "title": f"第 {episode_number} 集：雨夜来信",
        "source_chapter_start": 1,
        "source_chapter_end": 1,
        "target_duration_seconds": 45,
        "episode_goal": "主角确认匿名来信与姐姐失踪案有关。",
        "closing_hook": "仓库深处传来金属碰撞声。",
        "source_chunk_ids": source_chunk_ids or [CHUNK_1],
    }
    data.update(overrides)
    return EpisodePlan(**data)


def test_two_episode_plans_can_be_created_from_current_manuscript_chunks():
    first = make_episode_plan(episode_number=1, source_chunk_ids=[CHUNK_1])
    second = make_episode_plan(episode_number=2, source_chunk_ids=[CHUNK_1, CHUNK_2])

    plan_set = EpisodePlanSet(project_id=PROJECT_ID, plans=[first, second])

    assert [plan.episode_number for plan in plan_set.plans] == [1, 2]
    assert plan_set.plans[1].source_chunk_ids == [CHUNK_1, CHUNK_2]


def test_episode_plan_requires_episode_goal():
    with pytest.raises(ValidationError, match="episode_goal"):
        make_episode_plan(episode_goal="")


def test_episode_plan_rejects_duplicate_source_chunk_ids():
    with pytest.raises(ValidationError, match="source_chunk_ids 不能重复"):
        make_episode_plan(source_chunk_ids=[CHUNK_1, CHUNK_1])


def test_episode_plan_set_rejects_project_id_mismatch():
    first = make_episode_plan(episode_number=1)
    second = make_episode_plan(episode_number=2, project_id="another-project")

    with pytest.raises(ValidationError, match="project_id 必须一致"):
        EpisodePlanSet(project_id=PROJECT_ID, plans=[first, second])


def test_episode_plan_set_rejects_episode_number_gap():
    first = make_episode_plan(episode_number=1)
    third = make_episode_plan(episode_number=3)

    with pytest.raises(ValidationError, match="连续递增"):
        EpisodePlanSet(project_id=PROJECT_ID, plans=[first, third])


def test_episode_plan_set_normalizes_source_chunk_ids():
    plan = make_episode_plan(source_chunk_ids=[f" {CHUNK_1} "])

    assert plan.source_chunk_ids == [CHUNK_1]
