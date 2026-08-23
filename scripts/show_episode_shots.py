"""查看某集分镜、已提交视频任务及当前可播放 URL。"""

from __future__ import annotations

import argparse

from narrative.runtime import create_narrative_runtime
from narrative.video_task_repository import MySQLShotVideoTaskStore
from video.mysql_config import load_mysql_settings
from video.provider_factory import create_provider_bundle
from video.repository import MySQLVideoJobRepository
from video.service import VideoGenerationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--episode-number", type=int, default=1)
    parser.add_argument("--provider", choices=["mock", "runway", "seedance"], default="runway")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="向 Provider 查询尚未完成任务的最新状态；不产生生成费用。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    runtime = create_narrative_runtime()
    storyboard = runtime.repository.get_prioritized_storyboard(
        args.project_id, args.episode_number
    )
    if storyboard is None:
        raise SystemExit("[失败] 找不到该集已保存的优先级分镜。")

    settings = load_mysql_settings()
    task_store = MySQLShotVideoTaskStore(settings)
    task_store.setup()
    repository = MySQLVideoJobRepository(settings)
    repository.setup()
    links = {link.shot_id: link for link in task_store.list_episode(
        args.project_id, args.episode_number
    )}
    service = None
    if args.refresh:
        bundle = create_provider_bundle(args.provider)
        service = VideoGenerationService(
            bundle.provider, repository, models=bundle.models
        )

    for shot in storyboard.shots:
        link = links.get(shot.shot_id)
        if link is None:
            print(f"{shot.shot_id} | 未提交 | {shot.visual_prompt}")
            continue
        try:
            job = service.get_job(link.video_job_id) if service else repository.get(link.video_job_id)
        except (RuntimeError, ValueError) as error:
            print(f"{shot.shot_id} | 查询失败：{error} | task={link.video_job_id}")
            continue
        if job is None:
            print(f"{shot.shot_id} | 任务记录缺失 | task={link.video_job_id}")
            continue
        print(f"{shot.shot_id} | {job.status.value} | task={job.job_id}")
        print(f"  分镜：{shot.visual_prompt}")
        print(f"  视频：{job.output_url or '尚未生成可播放 URL'}")


if __name__ == "__main__":
    main()
