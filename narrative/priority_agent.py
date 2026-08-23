"""为已完成分镜分配视频质量下限的确定性 Priority Agent。"""

from narrative.schemas import PrioritizedShot, PrioritizedStoryboard, ShotImportance, Storyboard


class PriorityAgent:
    """v1 采用可测试规则，避免模型把所有镜头都判为关键镜头而失去成本控制。"""

    def prioritize(self, storyboard: Storyboard) -> PrioritizedStoryboard:
        key_orders = {1, len(storyboard.shots)}
        # 关键叙事物件的特写值得使用更高质量模型，但关键镜头最多 3 个。
        for shot in storyboard.shots:
            if len(key_orders) >= 3:
                break
            if any(word in shot.visual_prompt for word in ("特写", "信纸", "铁盒", "照片", "纸条")):
                key_orders.add(shot.order)
        shots = [
            PrioritizedShot(
                **shot.model_dump(),
                importance=ShotImportance.KEY if shot.order in key_orders else ShotImportance.STANDARD,
                priority_reason=("开场、叙事物件或结尾悬念，决定观众理解与视觉连续性。" if shot.order in key_orders else "用于衔接动作和环境信息，可优先控制成本。"),
                min_quality_score=8 if shot.order in key_orders else 5,
            )
            for shot in storyboard.shots
        ]
        return PrioritizedStoryboard(project_id=storyboard.project_id, episode_number=storyboard.episode_number, target_duration_seconds=storyboard.target_duration_seconds, shots=shots)
