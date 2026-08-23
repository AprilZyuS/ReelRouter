"""项目长期叙事状态的单元测试。"""

import pytest
from pydantic import ValidationError

from narrative.repository import InMemoryNarrativeKnowledgeRepository
from narrative.schemas import NarrativeProjectProfile


def make_profile(**overrides: object) -> NarrativeProjectProfile:
    data: dict[str, object] = {
        "project_id": "rain-letter",
        "manuscript_document_id": "rain-letter-manuscript-v1",
        "title": "雨夜来信",
        "logline": "匿名来信让林舟重新追查姐姐失踪案。",
        "style_bible": "都市悬疑，雨夜冷色调，克制的电影感镜头。",
        "planned_episode_count": 6,
    }
    data.update(overrides)
    return NarrativeProjectProfile(**data)


def test_project_profile_is_valid():
    profile = make_profile()

    assert profile.project_id == "rain-letter"
    assert profile.planned_episode_count == 6


def test_project_profile_rejects_missing_style_bible():
    with pytest.raises(ValidationError, match="style_bible"):
        make_profile(style_bible="")


def test_in_memory_repository_saves_and_loads_project_profile():
    repository = InMemoryNarrativeKnowledgeRepository()
    profile = make_profile()

    repository.save_project_profile(profile)

    assert repository.get_project_profile(profile.project_id) == profile


def test_in_memory_repository_returns_none_for_unknown_project_profile():
    repository = InMemoryNarrativeKnowledgeRepository()

    assert repository.get_project_profile("missing-project") is None


def test_saving_same_project_profile_replaces_old_value():
    repository = InMemoryNarrativeKnowledgeRepository()
    original = make_profile()
    updated = make_profile(
        manuscript_document_id="rain-letter-manuscript-v2",
        title="雨夜来信：重写版",
        planned_episode_count=8,
    )

    repository.save_project_profile(original)
    repository.save_project_profile(updated)

    assert repository.get_project_profile(updated.project_id) == updated
