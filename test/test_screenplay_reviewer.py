"""Screenplay Reviewer 的结构化结论与失败保护测试。"""

import json

import pytest

from narrative.schemas import ContextPack, EpisodePlan, Screenplay, ScreenplayScene, SourceChunk
from narrative.screenplay_reviewer import ScreenplayReviewOutputError, ScreenplayReviewer


class FakeClient:
    def __init__(self, response: dict):
        self.response = json.dumps(response, ensure_ascii=False)
        self.prompts: list[str] = []

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append(user_prompt)
        return self.response


def make_context_and_screenplay():
    episode = EpisodePlan(
        project_id="review-project",
        episode_number=1,
        title="第一集",
        source_chapter_start=1,
        source_chapter_end=1,
        target_duration_seconds=45,
        episode_goal="主角收到匿名信。",
        closing_hook="仓库门后传来脚步声。",
        source_chunk_ids=["c1"],
    )
    context = ContextPack(
        episode=episode,
        source_chunks=[SourceChunk(chunk_id="c1", chapter_number=1, content="主角收到匿名信，仓库门后传来脚步声。", relevance_score=1)],
        style_bible="冷色悬疑",
    )
    screenplay = Screenplay(
        project_id="review-project",
        episode_number=1,
        target_duration_seconds=45,
        scenes=[
                ScreenplayScene(scene_id="s1", order=1, narration="她收到匿名信。", visual_description="雨夜。", duration_seconds=15, source_chunk_ids=["c1"]),
                ScreenplayScene(scene_id="s2", order=2, narration="她走向仓库。", visual_description="港口。", duration_seconds=15, source_chunk_ids=["c1"]),
                ScreenplayScene(scene_id="s3", order=3, narration="脚步声响起。", visual_description="门后黑暗。", duration_seconds=15, source_chunk_ids=["c1"]),
        ],
    )
    return context, screenplay


def test_reviewer_returns_passing_review_with_episode_summary():
    context, screenplay = make_context_and_screenplay()
    client = FakeClient({
        "passed": True,
        "feedback": "本集边界清晰。",
        "violations": [],
        "episode_summary": {"episode_number": 1, "recap": "主角收到匿名信并听见脚步声。", "unresolved_loops": ["脚步声是谁？"]},
    })

    result = ScreenplayReviewer(client).review(context, screenplay)

    assert result.passed is True
    assert result.episode_summary is not None
    assert "candidate_screenplay" in client.prompts[0]


def test_reviewer_rejects_failed_result_without_violations():
    context, screenplay = make_context_and_screenplay()
    client = FakeClient({
        "passed": False,
        "feedback": "不通过。",
        "violations": [],
        "episode_summary": None,
    })

    with pytest.raises(ScreenplayReviewOutputError, match="violations"):
        ScreenplayReviewer(client, max_format_retries=0).review(context, screenplay)
