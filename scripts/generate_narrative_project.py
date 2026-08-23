"""手动执行一次“方舟模型写小说 → MySQL/FAISS 知识库”的真实冒烟测试。"""

from __future__ import annotations

import argparse
from pathlib import Path
import re

from narrative.ark_story_writer import ArkResponseError
from narrative.runtime import create_narrative_runtime
from narrative.schemas import NarrativeProjectRequest
from narrative.story_writer import StoryWriterOutputError


PROJECT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,40}")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_project_id(value: str) -> str:
    """限制项目 ID，确保其既能写入数据库，也能作为安全的 FAISS 目录名。"""
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
        help="确认本次会调用方舟模型；格式校验失败时最多重试一次，可能产生两次小额模型费用。",
    )
    parser.add_argument("--project-id", type=parse_project_id, required=True)
    parser.add_argument("--title", default="雨夜来信")
    parser.add_argument(
        "--keywords",
        default="匿名来信,姐姐失踪,港口仓库",
        help="用英文逗号分隔，最多 8 个关键词。",
    )
    parser.add_argument("--genre", default="都市悬疑")
    parser.add_argument("--visual-style", default="冷色调电影感，雨夜霓虹，克制悬疑")
    parser.add_argument("--episode-duration-seconds", type=int, default=45)
    parser.add_argument("--episode-budget-usd", type=float, default=2.5)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.confirm_paid_call:
        raise SystemExit("已取消：请显式添加 --confirm-paid-call 后再进行真实模型调用。")

    print("[准备] 正在校验创作参数。", flush=True)
    keywords = [keyword.strip() for keyword in args.keywords.split(",") if keyword.strip()]
    request = NarrativeProjectRequest(
        project_id=args.project_id,
        title=args.title,
        keywords=keywords,
        genre=args.genre,
        visual_style=args.visual_style,
        episode_duration_seconds=args.episode_duration_seconds,
        episode_budget_usd=args.episode_budget_usd,
    )

    # 重跑同一项目会创建新的叙事版本，并使旧计划、剧本和分镜失效；历史
    # 原文保留，但 FAISS current 指针只检索当前版本。
    print("[准备] 正在初始化 MySQL、BGE-M3、FAISS 与 Story Writer。", flush=True)
    runtime = create_narrative_runtime(
        index_root=PROJECT_ROOT / "data" / "narrative_indexes",
        progress_callback=lambda message: print(f"[流程] {message}", flush=True),
    )
    try:
        result = runtime.generation_service.generate_and_ingest(request)
    except ArkResponseError as error:
        print("[失败] 阶段 1/4：方舟请求已完成，但模型未产出可用正文。", flush=True)
        print(f"[失败] {error}", flush=True)
        print("[说明] 小说尚未写入 MySQL，FAISS 索引也尚未构建。", flush=True)
        raise SystemExit(1) from error
    except StoryWriterOutputError as error:
        print("[失败] 阶段 1/4：模型输出未通过 JSON/数据契约校验。", flush=True)
        print(f"[失败] {error}", flush=True)
        print("[说明] 小说尚未写入 MySQL，FAISS 索引也尚未构建。", flush=True)
        raise SystemExit(1) from error

    print("[检索] 正在从刚建立的项目 FAISS 索引回查原文证据。", flush=True)
    evidence = runtime.retriever.retrieve(
        request.project_id,
        " ".join(request.keywords),
        limit=2,
    )

    print("生成并入库成功。")
    print(f"项目 ID：{result.manuscript.project_id}")
    print(f"文档 ID：{result.document.document_id}")
    print(f"小说标题：{result.manuscript.title}")
    print(f"小说正文字符数：{len(result.manuscript.manuscript)}")
    print(f"建议集数：{result.manuscript.planned_episode_count}")
    print(f"MySQL 分块数：{result.ingestion.chunk_count}")
    print("FAISS 检索到的 chunk_id：", [chunk.chunk_id for chunk in evidence])


if __name__ == "__main__":
    main()
