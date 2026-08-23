"""将某集全部“完成且人工接受”的镜头视频用 FFmpeg 拼接为成片。"""

from __future__ import annotations

import argparse
from pathlib import Path

from narrative.assembly import FfmpegEpisodeAssembler, build_episode_assembly_plan
from narrative.runtime import create_narrative_runtime
from narrative.video_task_repository import MySQLShotVideoTaskStore
from video.mysql_config import load_mysql_settings
from video.repository import MySQLVideoJobRepository


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--episode-number", type=int, default=1)
    parser.add_argument(
        "--output-path",
        type=Path,
        help="默认 data/outputs/<project-id>/episode-<n>.mp4。",
    )
    parser.add_argument(
        "--confirm-assembly",
        action="store_true",
        help="确认开始下载已审核的 Provider 视频并执行本地 FFmpeg 合成。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.confirm_assembly:
        raise SystemExit("已取消：请显式添加 --confirm-assembly。")
    runtime = create_narrative_runtime()
    profile = runtime.repository.get_project_profile(args.project_id)
    storyboard = runtime.repository.get_prioritized_storyboard(
        args.project_id, args.episode_number
    )
    if profile is None or storyboard is None:
        raise SystemExit("[失败] 需要项目 Profile 和已保存的优先级分镜。")
    if not profile.enable_assembly:
        raise SystemExit("[失败] 该项目 Profile 已关闭 FFmpeg 合成。")

    settings = load_mysql_settings()
    task_store = MySQLShotVideoTaskStore(settings)
    task_store.setup()
    links = task_store.list_episode(args.project_id, args.episode_number)
    job_repository = MySQLVideoJobRepository(settings)
    job_repository.setup()
    jobs = [job_repository.get(link.video_job_id) for link in links]
    output_path = args.output_path or (
        PROJECT_ROOT
        / "data"
        / "outputs"
        / args.project_id
        / f"episode-{args.episode_number}.mp4"
    )
    try:
        plan = build_episode_assembly_plan(
            storyboard,
            links,
            [job for job in jobs if job is not None],
            output_path,
        )
        result = FfmpegEpisodeAssembler().assemble(plan)
    except (ValueError, RuntimeError) as error:
        raise SystemExit(f"[失败] 无法合成：{error}") from error
    print(f"[完成] 成片已生成：{result.resolve()}")


if __name__ == "__main__":
    main()
