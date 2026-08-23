"""调用 Reviewer 审查候选剧本；审查通过后仍需人工批准。"""

from __future__ import annotations

import argparse
from pathlib import Path

from narrative.ark_story_writer import ArkResponseError, ArkStoryWriterClient
from narrative.runtime import create_narrative_runtime
from narrative.screenplay_reviewer import (
    ScreenplayReviewer,
    ScreenplayReviewOutputError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--confirm-paid-call",
        action="store_true",
        help="确认本次会调用方舟模型；格式失败时最多重试一次，可能产生两次小额模型费用。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.confirm_paid_call:
        raise SystemExit("已取消：请显式添加 --confirm-paid-call 后再调用 Reviewer。")

    runtime = create_narrative_runtime(
        index_root=PROJECT_ROOT / "data" / "narrative_indexes",
    )
    candidate = runtime.repository.get_screenplay_candidate(args.candidate_id)
    if candidate is None:
        raise SystemExit("[失败] 候选剧本不存在。")

    plans = runtime.repository.list_episode_plans(candidate.screenplay.project_id)
    episode = next(
        (
            plan
            for plan in plans
            if plan.episode_number == candidate.screenplay.episode_number
        ),
        None,
    )
    if episode is None:
        raise SystemExit("[失败] 候选剧本对应的 EpisodePlan 不存在或已失效。")

    try:
        context = runtime.context_manager.build(episode)
        print("[流程] 正在请求 Screenplay Reviewer 审查候选稿。", flush=True)
        review = ScreenplayReviewer(
            ArkStoryWriterClient(),
            progress_callback=lambda message: print(f"[流程] {message}", flush=True),
        ).review(context, candidate.screenplay)
        stored = runtime.repository.record_screenplay_review(
            candidate.candidate_id,
            review,
        )
    except ArkResponseError as error:
        print(f"[失败] Reviewer 未返回可用文本：{error}", flush=True)
        raise SystemExit(1) from error
    except (ScreenplayReviewOutputError, ValueError) as error:
        print(f"[失败] Reviewer 输出未通过校验：{error}", flush=True)
        raise SystemExit(1) from error

    print("审查结果已保存，尚未自动发布。")
    print(f"候选剧本 ID：{stored.candidate_id}")
    print("通过：", "是" if stored.review.passed else "否")
    print("反馈：", stored.review.feedback)
    if stored.review.violations:
        print("问题：", "；".join(stored.review.violations))
    if stored.review.passed:
        print("下一步：人工确认后运行 scripts.approve_screenplay 发布该剧本。")


if __name__ == "__main__":
    main()
