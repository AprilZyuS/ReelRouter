"""把已保存的优先级分镜预检并提交为逐镜头视频任务。"""

from __future__ import annotations

import argparse

from narrative.runtime import create_narrative_runtime
from narrative.video_execution import (
    EpisodeBudgetExceeded,
    EpisodePartialSubmissionError,
    EpisodeVideoExecutor,
    VideoExecutionApprovalRequired,
)
from narrative.video_task_repository import MySQLShotVideoTaskStore
from narrative.visual_assets import MySQLShotReferenceAssetStore
from video.mysql_config import load_mysql_settings
from video.provider_factory import create_provider_bundle
from video.repository import MySQLVideoJobRepository
from video.service import VideoGenerationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--episode-number", type=int, default=1)
    parser.add_argument(
        "--provider", choices=["mock", "runway", "seedance"], default="mock",
        help="默认 mock，不会调用真实视频 Provider。",
    )
    parser.add_argument(
        "--require-reference-assets", action="store_true",
        help="要求该集每个镜头都有登记的参考图，使用 image-to-video。",
    )
    parser.add_argument(
        "--confirm-video-execution", action="store_true",
        help="确认将按预估成本把镜头提交给指定 Provider。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.episode_number < 1:
        raise SystemExit("[失败] episode-number 必须为正整数。")

    narrative_runtime = create_narrative_runtime()
    profile = narrative_runtime.repository.get_project_profile(args.project_id)
    storyboard = narrative_runtime.repository.get_prioritized_storyboard(
        args.project_id, args.episode_number
    )
    if profile is None or storyboard is None:
        raise SystemExit("[失败] 需要项目 Profile 和已保存的优先级分镜。")

    settings = load_mysql_settings()
    video_repository = MySQLVideoJobRepository(settings)
    video_repository.setup()
    task_store = MySQLShotVideoTaskStore(settings)
    task_store.setup()
    asset_store = MySQLShotReferenceAssetStore(settings)
    asset_store.setup()
    bundle = create_provider_bundle(args.provider)
    service = VideoGenerationService(
        bundle.provider, video_repository, models=bundle.models
    )
    executor = EpisodeVideoExecutor(service, task_store)
    assets = {
        asset.shot_id: asset
        for asset in asset_store.list_episode(args.project_id, args.episode_number)
    }
    try:
        plan = executor.build_plan(
            profile,
            storyboard,
            reference_assets=assets,
            require_reference_assets=args.require_reference_assets,
        )
    except (EpisodeBudgetExceeded, ValueError) as error:
        raise SystemExit(f"[失败] 提交前预检未通过：{error}") from error

    print(
        f"[预检] 第 {plan.episode_number} 集共 {len(plan.shots)} 个镜头，"
        f"预估总成本 ${plan.estimated_total_usd:.2f} / "
        f"单集预算 ${plan.episode_budget_usd:.2f}。"
    )
    for item in plan.shots:
        print(
            f"  {item.shot_id}: {item.selection.model.model_id} | "
            f"${item.selection.estimated_cost_usd:.2f} | "
            f"{item.request.mode.value}"
        )
    try:
        links = executor.submit_plan(
            plan, confirmed=args.confirm_video_execution
        )
    except VideoExecutionApprovalRequired as error:
        raise SystemExit(f"[未提交] {error}") from error
    except EpisodePartialSubmissionError as error:
        print(f"[部分提交] {error}")
        for link in error.links:
            print(f"  已保存：{link.shot_id} -> {link.video_job_id}")
        raise SystemExit(
            "请修复 Provider 错误后使用相同命令重试；已提交镜头不会重复提交。"
        ) from error

    print(f"[已提交] Provider={bundle.provider_name}，共 {len(links)} 个异步任务。")
    for link in links:
        print(f"  {link.shot_id} -> {link.video_job_id} ({link.model_id})")
    print("下一步：运行 scripts.poll_episode_videos 查询状态；完成后进行输出评审与合成。")


if __name__ == "__main__":
    main()
