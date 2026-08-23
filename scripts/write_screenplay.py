"""从已保存的 EpisodePlan 和 Context Pack 生成一集结构化剧本。"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from uuid import uuid4

from narrative.ark_story_writer import ArkResponseError, ArkStoryWriterClient
from narrative.runtime import create_narrative_runtime
from narrative.screenwriter import Screenwriter, ScreenwriterOutputError
from narrative.schemas import ScreenplayCandidate


PROJECT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,40}")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_project_id(value: str) -> str:
    """限制项目 ID，使其可安全对应既有 MySQL 与 FAISS 项目记录。"""
    if not PROJECT_ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "project-id 只能包含字母、数字、下划线和连字符，长度不超过 40。"
        )
    return value


def parse_episode_number(value: str) -> int:
    """限制集号，避免将任意字符串传入数据库查询。"""
    try:
        episode_number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("episode-number 必须是正整数。") from error
    if episode_number < 1:
        raise argparse.ArgumentTypeError("episode-number 必须是正整数。")
    return episode_number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-paid-call",
        action="store_true",
        help="确认本次会调用方舟模型；格式失败时最多重试一次，可能产生两次小额模型费用。",
    )
    parser.add_argument("--project-id", type=parse_project_id, required=True)
    parser.add_argument(
        "--episode-number",
        type=parse_episode_number,
        default=1,
        help="要生成剧本的集号，默认第 1 集。第 2 集需要先有审核通过的第 1 集总结。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.confirm_paid_call:
        raise SystemExit("已取消：请显式添加 --confirm-paid-call 后再调用模型。")

    print("[准备] 正在读取 MySQL 中已保存的分集计划。", flush=True)
    runtime = create_narrative_runtime(
        index_root=PROJECT_ROOT / "data" / "narrative_indexes",
    )
    plans = runtime.repository.list_episode_plans(args.project_id)
    episode = next(
        (plan for plan in plans if plan.episode_number == args.episode_number),
        None,
    )
    if episode is None:
        raise SystemExit(
            f"[失败] 项目 {args.project_id} 没有已保存的第 {args.episode_number} 集计划。"
        )

    print("[流程] 正在构建带 RAG 原文证据的 Context Pack。", flush=True)
    try:
        context = runtime.context_manager.build(episode)
    except ValueError as error:
        print("[失败] 当前集缺少构建 Context Pack 所需的长期记忆。", flush=True)
        print(f"[失败] {error}", flush=True)
        print("[说明] 第 2 集必须等待第 1 集通过一致性审核并写入总结后才能创作。", flush=True)
        raise SystemExit(1) from error

    writer = Screenwriter(
        ArkStoryWriterClient(),
        progress_callback=lambda message: print(f"[流程] {message}", flush=True),
    )
    print("[流程] 正在请求 Screenwriter 生成结构化剧本。", flush=True)
    try:
        screenplay = writer.write(context)
    except ArkResponseError as error:
        print("[失败] 方舟请求已完成，但模型未产出可用正文。", flush=True)
        print(f"[失败] {error}", flush=True)
        raise SystemExit(1) from error
    except ScreenwriterOutputError as error:
        print("[失败] 模型输出未通过剧本 JSON/业务校验。", flush=True)
        print(f"[失败] {error}", flush=True)
        print("[说明] 本次剧本未写入长期记忆，项目数据没有被改动。", flush=True)
        raise SystemExit(1) from error

    candidate = ScreenplayCandidate(
        candidate_id=f"sc-{uuid4().hex}",
        screenplay=screenplay,
    )
    runtime.repository.save_screenplay_candidate(candidate)

    print("剧本生成成功，已保存为候选草稿；尚未批准，不会覆盖已批准剧本。")
    print(f"候选剧本 ID：{candidate.candidate_id}")
    print(
        f"项目：{screenplay.project_id} | 第 {screenplay.episode_number} 集 | "
        f"总时长：{screenplay.target_duration_seconds} 秒"
    )
    for scene in screenplay.scenes:
        print(
            f"\n场景 {scene.order}：{scene.scene_id}（{scene.duration_seconds} 秒）\n"
            f"旁白：{scene.narration}\n"
            f"对白：{scene.dialogue or '无'}\n"
            f"画面：{scene.visual_description}\n"
            f"证据：{scene.source_chunk_ids}",
            flush=True,
        )


if __name__ == "__main__":
    main()
