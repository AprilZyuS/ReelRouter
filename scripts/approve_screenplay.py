"""人工批准已通过 Reviewer 的候选剧本，并写入跨集摘要。"""

from __future__ import annotations

import argparse
from pathlib import Path

from narrative.runtime import create_narrative_runtime


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--confirm-human-approval",
        action="store_true",
        help="确认你已经人工查看候选剧本及 Reviewer 结论，并同意发布。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.confirm_human_approval:
        raise SystemExit("已取消：人工发布必须显式添加 --confirm-human-approval。")

    runtime = create_narrative_runtime(
        index_root=PROJECT_ROOT / "data" / "narrative_indexes",
    )
    try:
        approved = runtime.repository.approve_screenplay_candidate(args.candidate_id)
    except (LookupError, ValueError) as error:
        raise SystemExit(f"[失败] 无法发布候选剧本：{error}") from error

    screenplay = approved.screenplay
    print("候选剧本已人工批准并写入长期记忆。")
    print(f"项目：{screenplay.project_id} | 第 {screenplay.episode_number} 集")
    print("已生成 EpisodeSummary；下一集 Context Pack 可自动读取该摘要。")


if __name__ == "__main__":
    main()
