import json

import pytest

from narrative.schemas import ContextPack, EpisodePlan, Screenplay, ScreenplayScene, SourceChunk
from narrative.storyboard_writer import (
    StoryboardOutputError,
    StoryboardVideoConstraints,
    StoryboardWriter,
)
from video.model_registry import build_seedance_model


class FakeClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        return self.response


def context_and_screenplay() -> tuple[ContextPack, Screenplay]:
    episode = EpisodePlan(project_id="p", episode_number=1, title="第一集", source_chapter_start=1, source_chapter_end=1, target_duration_seconds=45, episode_goal="收到信。", closing_hook="铁盒揭开危险。", source_chunk_ids=["c1"])
    context = ContextPack(episode=episode, source_chunks=[SourceChunk(chunk_id="c1", chapter_number=1, content="雨夜里她收到匿名信并在仓库拿到铁盒。", relevance_score=1)], style_bible="冷色悬疑")
    screenplay = Screenplay(project_id="p", episode_number=1, target_duration_seconds=45, scenes=[
        ScreenplayScene(scene_id="scene-001", order=1, narration="她收到匿名信。", visual_description="邮筒前的雨夜。", duration_seconds=15, source_chunk_ids=["c1"]),
        ScreenplayScene(scene_id="scene-002", order=2, narration="她前往仓库。", visual_description="港口仓库铁门。", duration_seconds=15, source_chunk_ids=["c1"]),
        ScreenplayScene(scene_id="scene-003", order=3, narration="她拿到铁盒。", visual_description="昏黄灯光下的铁盒。", duration_seconds=15, source_chunk_ids=["c1"]),
    ])
    return context, screenplay


def response(*, scene_id: str = "scene-001", chunk_id: str = "c1") -> str:
    durations = [8, 7, 8, 7, 8, 7]
    shots = [{"shot_id": f"shot-{i + 1:03d}", "scene_id": scene_id if i < 2 else f"scene-{(i // 2) + 1:03d}", "order": i + 1, "visual_prompt": "雨夜港口仓库，冷色调电影感。", "camera_instruction": "缓慢推进。", "duration_seconds": duration, "source_chunk_ids": [chunk_id]} for i, duration in enumerate(durations)]
    return json.dumps({"shots": shots}, ensure_ascii=False)


def test_create_returns_timed_evidence_backed_storyboard():
    context, screenplay = context_and_screenplay()
    result = StoryboardWriter(FakeClient(response())).create(context, screenplay)
    assert len(result.shots) == 6
    assert sum(shot.duration_seconds for shot in result.shots) == 45


def test_create_rejects_unknown_scene_or_evidence():
    context, screenplay = context_and_screenplay()
    with pytest.raises(StoryboardOutputError, match="scene_id"):
        StoryboardWriter(FakeClient(response(scene_id="unknown")), max_format_retries=0).create(context, screenplay)
    with pytest.raises(StoryboardOutputError, match="source_chunk_ids"):
        StoryboardWriter(FakeClient(response(chunk_id="other")), max_format_retries=0).create(context, screenplay)


def test_seedance_constraints_limit_a_45_second_episode_to_eleven_shots():
    constraints = StoryboardVideoConstraints.from_video_models(
        (build_seedance_model(cost_per_second=0.15),),
        target_duration_seconds=45,
    )

    assert constraints.min_duration_seconds == 4
    assert constraints.max_shot_count == 11
    assert "6 到 11 项" in StoryboardWriter._system_prompt(constraints)
    assert "4-10 秒" in StoryboardWriter._system_prompt(constraints)


def test_storyboard_contract_error_identifies_the_invalid_field():
    context, screenplay = context_and_screenplay()
    payload = json.loads(response())
    del payload["shots"][0]["duration_seconds"]

    with pytest.raises(StoryboardOutputError, match="shots.0.duration_seconds"):
        StoryboardWriter(
            FakeClient(json.dumps(payload, ensure_ascii=False)),
            max_format_retries=0,
        ).create(context, screenplay)
