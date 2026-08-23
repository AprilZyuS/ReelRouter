import pytest
from pydantic import ValidationError

from narrative.schemas import NovelManuscript


def make_manuscript(**overrides) -> NovelManuscript:
    data = {
        "project_id": "rain-letter",
        "title": "雨夜来信",
        "logline": "一封匿名来信揭开姐姐失踪案的新线索。",
        "manuscript": "雨下了一整夜。" * 120,
        "style_bible": "都市悬疑，冷色调，克制叙事。",
        "planned_episode_count": 6,
    }
    data.update(overrides)
    return NovelManuscript(**data)


def test_novel_manuscript_is_valid():
    manuscript = make_manuscript()
    assert manuscript.project_id == "rain-letter"


def test_novel_manuscript_rejects_too_short_text():
    with pytest.raises(ValidationError):
        make_manuscript(manuscript="太短了")


def test_novel_manuscript_rejects_invalid_episode_count():
    with pytest.raises(ValidationError):
        make_manuscript(planned_episode_count=1)


def test_novel_manuscript_is_immutable():
    manuscript = make_manuscript()
    with pytest.raises(ValidationError):
        manuscript.title = "不能修改"