"""为旧版叙事项目补齐创建约束，不调用模型、不重写小说或派生资产。"""

from __future__ import annotations

import argparse
from pathlib import Path

from narrative.runtime import create_narrative_runtime
from narrative.schemas import NarrativeProjectProfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--keywords", required=True, help="英文逗号分隔，最多 8 个关键词。")
    parser.add_argument("--genre", required=True)
    parser.add_argument("--episode-duration-seconds", type=int, default=45)
    parser.add_argument("--episode-budget-usd", type=float, default=2.5)
    parser.add_argument("--disable-assembly", action="store_true")
    parser.add_argument(
        "--confirm-profile-update",
        action="store_true",
        help="确认这些参数就是该项目最初且后续 Agent 必须遵守的创作约束。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.confirm_profile_update:
        raise SystemExit("已取消：请显式添加 --confirm-profile-update。")
    keywords = [item.strip() for item in args.keywords.split(",") if item.strip()]
    if not keywords:
        raise SystemExit("[失败] keywords 至少需要一个非空关键词。")

    runtime = create_narrative_runtime(
        index_root=PROJECT_ROOT / "data" / "narrative_indexes",
    )
    profile = runtime.repository.get_project_profile(args.project_id)
    if profile is None:
        raise SystemExit("[失败] 项目不存在，无法升级 Profile。")

    try:
        upgraded = NarrativeProjectProfile.model_validate(
            {
                **profile.model_dump(),
            "keywords": keywords,
            "genre": args.genre,
            "episode_duration_seconds": args.episode_duration_seconds,
            "episode_budget_usd": args.episode_budget_usd,
            "enable_assembly": not args.disable_assembly,
            }
        )
        runtime.repository.save_project_profile(upgraded)
    except ValueError as error:
        raise SystemExit(f"[失败] Profile 参数无效：{error}") from error

    print("旧版项目 Profile 已补齐，不会重写小说、计划、剧本或分镜。")
    print(f"项目：{upgraded.project_id} | 版本：{upgraded.narrative_version}")
    print("关键词：", "、".join(upgraded.keywords))


if __name__ == "__main__":
    main()
