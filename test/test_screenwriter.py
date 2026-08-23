"""Screenwriter 的结构化剧本、时长和 RAG 证据边界测试。"""

import json

import pytest

from narrative.schemas import ContextPack, EpisodePlan, SourceChunk
from narrative.screenwriter import Screenwriter, ScreenwriterOutputError


PROJECT_ID = "rain-letter-demo"
CHUNK_1 = "rain-letter-demo-manuscript-v1-c0000"
CHUNK_2 = "rain-letter-demo-manuscript-v1-c0001"


class FakeScreenwriterClient:
    """记录提示词并返回预设模型文本，不调用真实 API。"""

    def __init__(self, response: str) -> None:
        self.response = response
        self.system_prompt: str | None = None
        self.user_prompts: list[str] = []

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompts.append(user_prompt)
        return self.response


class SequenceScreenwriterClient(FakeScreenwriterClient):
    """按顺序给出模型结果，用于验证格式重试上限。"""

    def __init__(self, responses: list[str]) -> None:
        super().__init__(response="")
        self.responses = responses

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompts.append(user_prompt)
        return self.responses.pop(0)


def make_context() -> ContextPack:
    return ContextPack(
        episode=EpisodePlan(
            project_id=PROJECT_ID,
            episode_number=1,
            title="第 1 集：雨夜来信",
            source_chapter_start=1,
            source_chapter_end=1,
            target_duration_seconds=45,
            episode_goal="林晓确认匿名来信与姐姐失踪案有关。",
            closing_hook="铁盒里的照片让林晓意识到有人正在监视她。",
            source_chunk_ids=[CHUNK_1, CHUNK_2],
        ),
        source_chunks=[
            SourceChunk(
                chunk_id=CHUNK_1,
                chapter_number=1,
                content="林晓在雨夜收到匿名信，信中说姐姐仍然活着。她前往港口仓库。",
                relevance_score=1.0,
            ),
            SourceChunk(
                chunk_id=CHUNK_2,
                chapter_number=1,
                content="神秘人递给林晓铁盒，盒中照片和警告纸条证明她已被盯上。",
                relevance_score=0.82,
            ),
        ],
        style_bible="冷色调电影感，雨夜霓虹，克制悬疑。",
    )


def valid_response(**overrides: object) -> str:
    payload: dict[str, object] = {
        "scenes": [
            {
                "scene_id": "scene-001",
                "order": 1,
                "narration": "雨夜里，林晓从旧邮筒取出一封没有署名的信。",
                "dialogue": "",
                "visual_description": "雨水打在邮筒上，林晓在霓虹反光中展开湿透的信纸。",
                "duration_seconds": 12,
                "source_chunk_ids": [CHUNK_1],
            },
            {
                "scene_id": "scene-002",
                "order": 2,
                "narration": "信中提到失踪多年的姐姐，林晓赶往港口仓库。",
                "dialogue": "姐姐？你真的还活着吗？",
                "visual_description": "林晓撑伞穿过湿漉漉的街道，远处仓库铁门半掩。",
                "duration_seconds": 11,
                "source_chunk_ids": [CHUNK_1],
            },
            {
                "scene_id": "scene-003",
                "order": 3,
                "narration": "仓库里，戴口罩的陌生人递给她一个旧铁盒。",
                "dialogue": "你姐姐让我把这个交给你。",
                "visual_description": "昏黄灯光下，陌生人的手从阴影里递出锈迹斑斑的铁盒。",
                "duration_seconds": 11,
                "source_chunk_ids": [CHUNK_1, CHUNK_2],
            },
            {
                "scene_id": "scene-004",
                "order": 4,
                "narration": "照片和警告纸条让林晓意识到，暗处的人已经盯上了她。",
                "dialogue": "",
                "visual_description": "铁盒内的合影被雨水映亮，林晓抬头望向仓库深处的黑暗。",
                "duration_seconds": 11,
                "source_chunk_ids": [CHUNK_2],
            },
        ]
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_write_returns_evidence_backed_screenplay_with_exact_duration():
    context = make_context()
    client = FakeScreenwriterClient(valid_response())

    screenplay = Screenwriter(client).write(context)

    assert screenplay.project_id == PROJECT_ID
    assert screenplay.episode_number == 1
    assert screenplay.target_duration_seconds == 45
    assert sum(scene.duration_seconds for scene in screenplay.scenes) == 45
    assert screenplay.scenes[-1].source_chunk_ids == [CHUNK_2]
    assert client.system_prompt is not None
    assert "source_chunk_ids" in client.system_prompt
    assert CHUNK_1 in client.user_prompts[0]
    assert "冷色调电影感" in client.user_prompts[0]


def test_write_rejects_scene_evidence_outside_context_pack():
    payload = json.loads(valid_response())
    payload["scenes"][2]["source_chunk_ids"] = ["another-project-c0000"]

    with pytest.raises(ScreenwriterOutputError, match="EpisodePlan 范围外"):
        Screenwriter(
            FakeScreenwriterClient(json.dumps(payload, ensure_ascii=False)),
            max_format_retries=0,
        ).write(make_context())


def test_write_rejects_scene_durations_that_do_not_sum_to_episode_duration():
    payload = json.loads(valid_response())
    payload["scenes"][3]["duration_seconds"] = 10

    with pytest.raises(ScreenwriterOutputError, match="Screenplay 数据契约"):
        Screenwriter(
            FakeScreenwriterClient(json.dumps(payload, ensure_ascii=False)),
            max_format_retries=0,
        ).write(make_context())


def test_write_rejects_spoken_text_that_cannot_fit_scene_duration():
    payload = json.loads(valid_response())
    payload["scenes"][0]["narration"] = "信息过载" * 25

    with pytest.raises(ScreenwriterOutputError, match="口播预算"):
        Screenwriter(
            FakeScreenwriterClient(json.dumps(payload, ensure_ascii=False)),
            max_format_retries=0,
        ).write(make_context())


def test_write_rejects_more_than_six_scenes_even_when_schema_allows_them():
    payload = json.loads(valid_response())
    payload["scenes"] = [
        {
            **payload["scenes"][0],
            "scene_id": f"scene-{number:03d}",
            "order": number,
            "duration_seconds": 5 if number < 7 else 15,
        }
        for number in range(1, 8)
    ]

    with pytest.raises(ScreenwriterOutputError, match="3 到 6 个场景"):
        Screenwriter(
            FakeScreenwriterClient(json.dumps(payload, ensure_ascii=False)),
            max_format_retries=0,
        ).write(make_context())


def test_write_retries_once_after_invalid_json():
    client = SequenceScreenwriterClient(["{\"scenes\":", valid_response()])
    progress: list[str] = []

    screenplay = Screenwriter(
        client,
        max_format_retries=1,
        progress_callback=progress.append,
    ).write(make_context())

    assert len(screenplay.scenes) == 4
    assert len(client.user_prompts) == 2
    assert "上一版输出未通过校验" in client.user_prompts[1]
    assert progress == [
        "Screenwriter 输出未通过 JSON/业务校验，正在进行第 1 次格式修复重试。"
    ]


def test_screenwriter_rejects_negative_format_retry_limit():
    with pytest.raises(ValueError, match="max_format_retries"):
        Screenwriter(FakeScreenwriterClient(valid_response()), max_format_retries=-1)
