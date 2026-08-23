from narrative.priority_agent import PriorityAgent
from narrative.schemas import Storyboard, StoryboardShot


def test_priority_agent_keeps_shots_and_caps_key_shots():
    storyboard = Storyboard(project_id="p", episode_number=1, target_duration_seconds=45, shots=[StoryboardShot(shot_id=f"s{i}", scene_id="scene-001", order=i, visual_prompt="铁盒特写" if i == 3 else "雨夜街道", camera_instruction="推进", duration_seconds=5 if i < 9 else 5, source_chunk_ids=["c1"]) for i in range(1, 10)])
    result = PriorityAgent().prioritize(storyboard)
    assert [shot.shot_id for shot in result.shots] == [shot.shot_id for shot in storyboard.shots]
    assert 1 <= sum(shot.importance.value == "key" for shot in result.shots) <= 3
    assert all(shot.min_quality_score >= 7 for shot in result.shots if shot.importance.value == "key")
