"""Episode Planner 的结构化输出和原文证据边界测试。"""

import json

import pytest

from narrative.chunking import ChunkingConfig, chunk_document
from narrative.episode_planner import EpisodePlanner, EpisodePlannerOutputError
from narrative.repository import InMemoryNarrativeKnowledgeRepository
from narrative.schemas import (
    NarrativeDocument,
    NarrativeProjectProfile,
    NarrativeProjectRequest,
)


PROJECT_ID = "rain-letter-demo"
DOCUMENT_ID = "rain-letter-demo-manuscript-v1"


class FakeEpisodePlannerClient:
    """记录模型输入并返回固定 JSON 的测试替身。"""

    def __init__(self, response: str) -> None:
        self.response = response
        self.system_prompt: str | None = None
        self.user_prompts: list[str] = []

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompts.append(user_prompt)
        return self.response


class SequenceEpisodePlannerClient(FakeEpisodePlannerClient):
    """按顺序返回响应，用于验证最多一次的格式修复重试。"""

    def __init__(self, responses: list[str]) -> None:
        super().__init__(response="")
        self.responses = responses

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompts.append(user_prompt)
        return self.responses.pop(0)


def make_request() -> NarrativeProjectRequest:
    return NarrativeProjectRequest(
        project_id=PROJECT_ID,
        title="雨夜来信",
        keywords=["匿名来信", "姐姐失踪", "港口仓库"],
        genre="都市悬疑",
        visual_style="冷色调电影感",
        episode_duration_seconds=45,
        episode_budget_usd=2.5,
    )


def setup_project() -> tuple[InMemoryNarrativeKnowledgeRepository, list[str]]:
    repository = InMemoryNarrativeKnowledgeRepository()
    document = NarrativeDocument(
        document_id=DOCUMENT_ID,
        project_id=PROJECT_ID,
        title="雨夜来信",
        source_type="text",
        raw_text=(
            "雨下了一整夜。林舟收到匿名来信，信中提到失踪七年的姐姐。"
            "她循着线索来到港口仓库，在角落发现一把生锈的钥匙。"
            "钥匙背面刻着姐姐的名字，仓库深处随即传来陌生人的脚步声。"
        )
        * 4,
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
            title="雨夜来信",
            logline="一封匿名来信重新揭开姐姐失踪案。",
            style_bible="冷色调电影感，雨夜霓虹，克制悬疑。",
            planned_episode_count=2,
        )
    )
    return repository, [chunk.chunk_id for chunk in chunks]


def valid_response(chunk_ids: list[str], **overrides: object) -> str:
    payload: dict[str, object] = {
        "project_id": "model-may-not-own-this",
        "plans": [
            {
                "episode_number": 1,
                "title": "第 1 集：雨夜来信",
                "source_chapter_start": 1,
                "source_chapter_end": 1,
                "target_duration_seconds": 45,
                "episode_goal": "林舟确认匿名来信和姐姐失踪案有关。",
                "closing_hook": "仓库深处传来陌生人的脚步声。",
                "source_chunk_ids": [chunk_ids[0]],
                "scope": {
                    "must_include": ["林舟收到匿名来信", "林舟决定前往仓库"],
                    "must_defer": ["钥匙背后的完整真相"],
                    "ending_beat": "仓库深处传来陌生人的脚步声。",
                },
            },
            {
                "episode_number": 2,
                "title": "第 2 集：港口钥匙",
                "source_chapter_start": 1,
                "source_chapter_end": 1,
                "target_duration_seconds": 45,
                "episode_goal": "林舟在港口仓库找到姐姐留下的线索。",
                "closing_hook": "钥匙打开的铁门后藏着新的秘密。",
                "source_chunk_ids": [chunk_ids[-1]],
                "scope": {
                    "must_include": ["林舟在仓库找到钥匙"],
                    "must_defer": ["铁门后的完整秘密"],
                    "ending_beat": "钥匙打开的铁门后藏着新的秘密。",
                },
            },
        ],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_planner_returns_two_validated_episode_plans_from_current_manuscript():
    repository, chunk_ids = setup_project()
    client = FakeEpisodePlannerClient(valid_response(chunk_ids))

    result = EpisodePlanner(client, repository).plan(make_request())

    assert result.project_id == PROJECT_ID
    assert [plan.episode_number for plan in result.plans] == [1, 2]
    assert all(plan.target_duration_seconds == 45 for plan in result.plans)
    assert result.plans[0].source_chunk_ids == [chunk_ids[0]]
    assert client.system_prompt is not None
    assert "只能引用用户提供的“可引用原文分块 ID”" in client.system_prompt
    assert "雨夜来信" in client.user_prompts[0]
    assert chunk_ids[0] in client.user_prompts[0]


def test_planner_rejects_wrong_plan_count():
    repository, chunk_ids = setup_project()
    payload = json.loads(valid_response(chunk_ids))
    payload["plans"] = payload["plans"][:1]

    with pytest.raises(EpisodePlannerOutputError, match="plans 数量"):
        EpisodePlanner(
            FakeEpisodePlannerClient(json.dumps(payload, ensure_ascii=False)),
            repository,
            max_format_retries=0,
        ).plan(make_request())


def test_planner_rejects_unknown_source_chunk_id():
    repository, chunk_ids = setup_project()
    payload = json.loads(valid_response(chunk_ids))
    payload["plans"][1]["source_chunk_ids"] = ["another-project-c0001"]

    with pytest.raises(EpisodePlannerOutputError, match="不存在的 source_chunk_ids"):
        EpisodePlanner(
            FakeEpisodePlannerClient(json.dumps(payload, ensure_ascii=False)),
            repository,
            max_format_retries=0,
        ).plan(make_request())


def test_planner_rejects_duration_that_violates_user_constraint():
    repository, chunk_ids = setup_project()
    payload = json.loads(valid_response(chunk_ids))
    payload["plans"][1]["target_duration_seconds"] = 30

    with pytest.raises(EpisodePlannerOutputError, match="target_duration_seconds"):
        EpisodePlanner(
            FakeEpisodePlannerClient(json.dumps(payload, ensure_ascii=False)),
            repository,
            max_format_retries=0,
        ).plan(make_request())


def test_planner_retries_once_after_invalid_json():
    repository, chunk_ids = setup_project()
    client = SequenceEpisodePlannerClient(["{\"plans\":", valid_response(chunk_ids)])
    progress: list[str] = []

    result = EpisodePlanner(
        client,
        repository,
        max_format_retries=1,
        progress_callback=progress.append,
    ).plan(make_request())

    assert len(result.plans) == 2
    assert len(client.user_prompts) == 2
    assert "上一版输出未通过校验" in client.user_prompts[1]
    assert progress == [
        "Episode Planner 输出未通过 JSON/业务校验，正在进行第 1 次格式修复重试。"
    ]


def test_planner_rejects_missing_profile_without_calling_model():
    client = FakeEpisodePlannerClient("{}")

    with pytest.raises(LookupError, match="NarrativeProjectProfile"):
        EpisodePlanner(client, InMemoryNarrativeKnowledgeRepository()).plan(
            make_request()
        )

    assert client.user_prompts == []


def test_planner_rejects_negative_retry_limit():
    repository, _ = setup_project()

    with pytest.raises(ValueError, match="max_format_retries"):
        EpisodePlanner(
            FakeEpisodePlannerClient("{}"),
            repository,
            max_format_retries=-1,
        )
