"""查询一集已提交的视频任务；支持在进程重启后继续轮询真实 Provider。"""

from __future__ import annotations

import argparse

from narrative.video_execution import EpisodeVideoExecutor
from narrative.video_task_repository import MySQLShotVideoTaskStore
from video.mysql_config import load_mysql_settings
from video.provider_factory import create_provider_bundle
from video.repository import MySQLVideoJobRepository
from video.service import VideoGenerationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--episode-number", type=int, default=1)
    parser.add_argument("--provider", choices=["mock", "runway", "seedance"], default="mock")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = load_mysql_settings()
    video_repository = MySQLVideoJobRepository(settings)
    video_repository.setup()
    task_store = MySQLShotVideoTaskStore(settings)
    task_store.setup()
    bundle = create_provider_bundle(args.provider)
    service = VideoGenerationService(
        bundle.provider, video_repository, models=bundle.models
    )
    jobs = EpisodeVideoExecutor(service, task_store).poll_episode(
        args.project_id, args.episode_number
    )
    if not jobs:
        raise SystemExit("[失败] 该集没有已提交的视频任务。")
    for job in jobs:
        print(
            f"{job.job_id} | {job.status.value} | {job.model_id} | "
            f"预估 ${job.cost.estimated_usd:.2f} | {job.output_url or '-'}"
        )
    if EpisodeVideoExecutor.is_terminal(jobs):
        print("[完成] 全部任务已到达终态；请评审每个完成视频后再合成。")
    else:
        print("[进行中] 尚有任务未完成；请稍后重复本命令。")


if __name__ == "__main__":
    main()
