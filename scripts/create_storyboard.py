"""将已批准剧本生成分镜，并保存供视频路由使用的优先级分镜。"""

from __future__ import annotations

import argparse
from pathlib import Path

from narrative.ark_story_writer import ArkResponseError, ArkStoryWriterClient
from narrative.priority_agent import PriorityAgent
from narrative.runtime import create_narrative_runtime
from narrative.storyboard_writer import StoryboardOutputError, StoryboardWriter


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--episode-number", type=int, default=1)
    parser.add_argument(
        "--confirm-paid-call",
        action="store_true",
        help="确认本次会调用方舟模型；格式失败时最多重试一次，可能产生两次小额模型费用。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.confirm_paid_call:
        raise SystemExit("已取消：请显式添加 --confirm-paid-call 后再生成分镜。")
    if args.episode_number < 1:
        raise SystemExit("[失败] episode-number 必须是正整数。")

    runtime = create_narrative_runtime(
        index_root=PROJECT_ROOT / "data" / "narrative_indexes",
    )
    screenplay = runtime.repository.get_screenplay(
        args.project_id,
        args.episode_number,
    )
    if screenplay is None:
        raise SystemExit("[失败] 只能为已人工批准的剧本生成分镜。")
    episode = next(
        (
            plan
            for plan in runtime.repository.list_episode_plans(args.project_id)
            if plan.episode_number == args.episode_number
        ),
        None,
    )
    if episode is None:
        raise SystemExit("[失败] 已批准剧本对应的 EpisodePlan 不存在。")

    try:
        context = runtime.context_manager.build(episode)
        print("[流程] 正在请求 Storyboard Writer 生成分镜。", flush=True)
        storyboard = StoryboardWriter(
            ArkStoryWriterClient(),
            progress_callback=lambda message: print(f"[流程] {message}", flush=True),
        ).create(context, screenplay)
    except ArkResponseError as error:
        print(f"[失败] Storyboard Writer 未返回可用文本：{error}", flush=True)
        raise SystemExit(1) from error
    except (StoryboardOutputError, ValueError) as error:
        print(f"[失败] 分镜未通过校验：{error}", flush=True)
        raise SystemExit(1) from error

    prioritized = PriorityAgent().prioritize(storyboard)
    runtime.repository.save_prioritized_storyboard(prioritized)
    print("分镜已生成并保存为优先级分镜。")
    for shot in prioritized.shots:
        print(
            f"镜头 {shot.order}：{shot.shot_id} | {shot.importance.value} | "
            f"最低质量 {shot.min_quality_score}",
            flush=True,
        )


if __name__ == "__main__":
    main()
