"""将人工批准的参考图版本绑定到一个已生成的分镜镜头。"""

from __future__ import annotations

import argparse

from narrative.runtime import create_narrative_runtime
from narrative.visual_assets import MySQLShotReferenceAssetStore, ShotReferenceAsset
from video.mysql_config import load_mysql_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--episode-number", type=int, required=True)
    parser.add_argument("--shot-id", required=True)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--asset-version", type=int, required=True)
    parser.add_argument("--reference-image-url", required=True)
    parser.add_argument(
        "--confirm-reference-asset",
        action="store_true",
        help="确认该 URL 对应已人工检查过的参考图版本。",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.confirm_reference_asset:
        raise SystemExit("已取消：请显式添加 --confirm-reference-asset。")
    runtime = create_narrative_runtime()
    storyboard = runtime.repository.get_prioritized_storyboard(
        args.project_id, args.episode_number
    )
    if storyboard is None:
        raise SystemExit("[失败] 该集不存在已保存的优先级分镜。")
    if args.shot_id not in {shot.shot_id for shot in storyboard.shots}:
        raise SystemExit("[失败] shot-id 不属于该集当前优先级分镜。")

    store = MySQLShotReferenceAssetStore(load_mysql_settings())
    store.setup()
    asset = ShotReferenceAsset(
        project_id=args.project_id,
        episode_number=args.episode_number,
        shot_id=args.shot_id,
        asset_id=args.asset_id,
        asset_version=args.asset_version,
        reference_image_url=args.reference_image_url,
    )
    store.save(asset)
    print(
        f"参考资产已绑定：第 {asset.episode_number} 集 {asset.shot_id} | "
        f"{asset.asset_id} v{asset.asset_version}"
    )


if __name__ == "__main__":
    main()
