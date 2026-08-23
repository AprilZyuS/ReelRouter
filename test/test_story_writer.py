import json

import pytest

from narrative.schemas import NarrativeProjectRequest
from narrative.story_writer import StoryWriter, StoryWriterOutputError


class FakeStoryWriterClient:
    """测试替身：记录提示词，并返回预先指定的模型文本。"""

    def __init__(self, response: str) -> None:
        self.response = response
        self.system_prompt: str | None = None
        self.user_prompt: str | None = None

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return self.response


class SequenceStoryWriterClient:
    """按顺序返回模型结果，用于验证格式修复重试边界。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.user_prompts: list[str] = []

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.user_prompts.append(user_prompt)
        return self.responses.pop(0)


def make_request() -> NarrativeProjectRequest:
    return NarrativeProjectRequest(
        project_id="rain-letter",
        title="雨夜来信",
        keywords=["匿名来信", "姐姐失踪", "港口仓库"],
        genre="都市悬疑",
        visual_style="冷色调电影感",
        episode_duration_seconds=45,
        episode_budget_usd=2.5,
    )


def valid_response(**overrides: object) -> str:
    """生成一份通过 NovelManuscript 校验的模型 JSON。"""
    payload: dict[str, object] = {
        "title": "雨夜来信",
        "logline": "一封匿名来信揭开姐姐失踪案的新线索。",
        "manuscript": "雨下了一整夜，港口的雾遮住了旧仓库。" * 80,
        "style_bible": "都市悬疑，冷色调，克制叙事。",
        "planned_episode_count": 6,
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_generate_returns_valid_novel_manuscript():
    client = FakeStoryWriterClient(valid_response())

    manuscript = StoryWriter(client).generate(make_request())

    assert manuscript.project_id == "rain-letter"
    assert manuscript.title == "雨夜来信"
    assert manuscript.planned_episode_count == 6
    assert client.system_prompt is not None
    assert client.user_prompt is not None
    assert "匿名来信" in client.user_prompt


def test_generate_keeps_project_id_owned_by_system():
    client = FakeStoryWriterClient(valid_response(project_id="another-project"))

    manuscript = StoryWriter(client).generate(make_request())

    assert manuscript.project_id == "rain-letter"


def test_generate_rejects_non_json_response():
    client = FakeStoryWriterClient("这是一篇小说，但不是 JSON。")

    with pytest.raises(StoryWriterOutputError, match="不是合法 JSON；响应字符数"):
        StoryWriter(client).generate(make_request())


def test_generate_rejects_manuscript_that_breaks_schema():
    client = FakeStoryWriterClient(valid_response(manuscript="太短了"))

    with pytest.raises(StoryWriterOutputError, match="不符合 NovelManuscript"):
        StoryWriter(client).generate(make_request())


def test_generate_retries_once_with_stricter_json_instruction():
    client = SequenceStoryWriterClient(["{\"title\":", valid_response()])
    progress: list[str] = []

    manuscript = StoryWriter(
        client,
        max_format_retries=1,
        progress_callback=progress.append,
    ).generate(make_request())

    assert manuscript.title == "雨夜来信"
    assert len(client.user_prompts) == 2
    assert "上一版输出未通过结构化校验" in client.user_prompts[1]
    assert "800 到 850" in client.user_prompts[1]
    assert progress == [
        "Story Writer 输出未通过 JSON/数据契约校验，正在进行第 1 次格式修复重试。"
    ]


def test_story_writer_rejects_negative_format_retry_limit():
    with pytest.raises(ValueError, match="max_format_retries"):
        StoryWriter(FakeStoryWriterClient(valid_response()), max_format_retries=-1)
