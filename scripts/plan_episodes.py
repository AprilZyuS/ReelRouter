"""为已入库的小说项目生成 ReelRouter v1 的前两集计划。"""

from __future__ import annotations

import argparse
from pathlib import Path
import re

from narrative.ark_story_writer import ArkResponseError, ArkStoryWriterClient
from narrative.episode_planner import EpisodePlanner, EpisodePlannerOutputError
from narrative.runtime import create_narrative_runtime
from narrative.schemas import NarrativeProjectRequest


PROJECT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,40}")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_EPISODE_COUNT = 2


def parse_project_id(value: str) -> str:
    """限制项目 ID，使其可安全用于既有 MySQL 与 FAISS 项目记录。"""
    if not PROJECT_ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "project-id 只能包含字母、数字、下划线和连字符，长度不超过 40。"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-paid-call",
        action="store_true",
        help="确认本次会调用方舟模型；格式失败时最多重试一次，可能产生两次小额模型费用。",
    )
    parser.add_argument("--project-id", type=parse_project_id, required=True)
    parser.add_argument(
        "--save",
        action="store_true",
        help="通过全部校验后，将本次两集计划作为该项目的当前计划写入 MySQL。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.confirm_paid_call:
        raise SystemExit("已取消：请显式添加 --confirm-paid-call 后再调用模型。")

    print("[准备] 正在加载项目长期状态与当前小说原文分块。", flush=True)
    runtime = create_narrative_runtime(
        index_root=PROJECT_ROOT / "data" / "narrative_indexes",
    )
    profile = runtime.repository.get_project_profile(args.project_id)
    if profile is None:
        raise SystemExit(f"[失败] 项目 {args.project_id} 不存在，不能规划分集。")
    if not profile.keywords:
        raise SystemExit(
            "[失败] 当前项目来自旧版 Profile，缺少创建时的关键词约束。"
            "请先重新运行 scripts.generate_narrative_project 发布新的叙事版本，"
            "再进行分集规划。"
        )

    # 后续创作必须忠实使用项目创建时保存的约束，不能由 CLI 重新伪造预算、
    # 题材或关键词。
    request = NarrativeProjectRequest(
        project_id=args.project_id,
        title=profile.title,
        keywords=profile.keywords,
        genre=profile.genre,
        visual_style=profile.style_bible,
        episode_duration_seconds=profile.episode_duration_seconds,
        episode_budget_usd=profile.episode_budget_usd,
        enable_assembly=profile.enable_assembly,
    )
    planner = EpisodePlanner(
        ArkStoryWriterClient(),
        runtime.repository,
        progress_callback=lambda message: print(f"[流程] {message}", flush=True),
    )

    print("[流程] 正在请求 Episode Planner 规划 v1 的前两集。", flush=True)
    try:
        plan_set = planner.plan(request, episode_count=V1_EPISODE_COUNT)
    except ArkResponseError as error:
        print("[失败] 方舟请求已完成，但模型未产出可用正文。", flush=True)
        print(f"[失败] {error}", flush=True)
        raise SystemExit(1) from error
    except EpisodePlannerOutputError as error:
        print("[失败] 模型输出未通过分集 JSON/业务校验。", flush=True)
        print(f"[失败] {error}", flush=True)
        print("[说明] 分集计划尚未持久化，原始小说与知识库没有被改动。", flush=True)
        raise SystemExit(1) from error

    if args.save:
        runtime.repository.save_episode_plan_set(plan_set)
        print("分集计划生成并已作为项目当前计划写入 MySQL。")
    else:
        print("分集计划生成成功（预览模式，未写入 MySQL）。")
    for plan in plan_set.plans:
        print(
            f"第 {plan.episode_number} 集：{plan.title}\n"
            f"  目标：{plan.episode_goal}\n"
            f"  悬念：{plan.closing_hook}\n"
            f"  原文证据：{plan.source_chunk_ids}",
            flush=True,
        )


if __name__ == "__main__":
    main()
