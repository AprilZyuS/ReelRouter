"""保存一个已完成镜头视频的人工输出评审。"""

from __future__ import annotations

import argparse

from video.mysql_config import load_mysql_settings
from video.output_review import VideoOutputReview
from video.repository import MySQLVideoJobRepository
from video.service import VideoGenerationService
from video.provider_factory import create_provider_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--provider", choices=["mock", "runway", "seedance"], default="mock")
    parser.add_argument("--accepted", choices=["true", "false"], required=True)
    parser.add_argument("--visual-quality-score", type=int, required=True)
    parser.add_argument("--prompt-alignment-score", type=int, required=True)
    parser.add_argument("--feedback", default="")
    parser.add_argument(
        "--confirm-human-review", action="store_true",
        help="确认分数和结论来自人工观看该视频后的判断。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.confirm_human_review:
        raise SystemExit("已取消：请显式添加 --confirm-human-review。")
    settings = load_mysql_settings()
    repository = MySQLVideoJobRepository(settings)
    repository.setup()
    bundle = create_provider_bundle(args.provider)
    service = VideoGenerationService(bundle.provider, repository, models=bundle.models)
    try:
        job = service.review_completed_job(
            args.job_id,
            VideoOutputReview(
                accepted=args.accepted == "true",
                visual_quality_score=args.visual_quality_score,
                prompt_alignment_score=args.prompt_alignment_score,
                feedback=args.feedback,
            ),
        )
    except ValueError as error:
        raise SystemExit(f"[失败] 无法保存评审：{error}") from error
    print(f"评审已保存：{job.job_id} | accepted={job.output_review.accepted}")


if __name__ == "__main__":
    main()
