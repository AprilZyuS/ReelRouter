"""镜头参考图资产的版本化登记与查询。

本模块不声称能让生成模型“绝对一致”。它把已人工批准的参考图版本绑定到
具体镜头，使 image-to-video 请求可以审计、复跑，并在缺少资产时阻止提交。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pymysql
from pymysql.cursors import DictCursor

from video.mysql_config import MySQLSettings


@dataclass(frozen=True)
class ShotReferenceAsset:
    project_id: str
    episode_number: int
    shot_id: str
    asset_id: str
    asset_version: int
    reference_image_url: str

    def __post_init__(self) -> None:
        if not self.reference_image_url.strip():
            raise ValueError("reference_image_url 不能为空。")
        if self.asset_version < 1:
            raise ValueError("asset_version 必须不小于 1。")


class ShotReferenceAssetStore(Protocol):
    def setup(self) -> None: ...

    def save(self, asset: ShotReferenceAsset) -> None: ...

    def list_episode(
        self, project_id: str, episode_number: int
    ) -> list[ShotReferenceAsset]: ...


class InMemoryShotReferenceAssetStore:
    def __init__(self) -> None:
        self._assets: dict[tuple[str, int, str], ShotReferenceAsset] = {}

    def setup(self) -> None:
        pass

    def save(self, asset: ShotReferenceAsset) -> None:
        self._assets[(asset.project_id, asset.episode_number, asset.shot_id)] = asset

    def list_episode(
        self, project_id: str, episode_number: int
    ) -> list[ShotReferenceAsset]:
        return sorted(
            (
                asset
                for asset in self._assets.values()
                if asset.project_id == project_id
                and asset.episode_number == episode_number
            ),
            key=lambda asset: asset.shot_id,
        )


class MySQLShotReferenceAssetStore:
    def __init__(self, settings: MySQLSettings) -> None:
        self.settings = settings

    def _connect(self):
        return pymysql.connect(
            host=self.settings.host,
            port=self.settings.port,
            user=self.settings.user,
            password=self.settings.password,
            database=self.settings.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )

    def setup(self) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_shot_reference_assets (
                        project_id VARCHAR(64) NOT NULL,
                        episode_number INT UNSIGNED NOT NULL,
                        shot_id VARCHAR(64) NOT NULL,
                        asset_id VARCHAR(128) NOT NULL,
                        asset_version INT UNSIGNED NOT NULL,
                        reference_image_url TEXT NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        PRIMARY KEY (project_id, episode_number, shot_id)
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save(self, asset: ShotReferenceAsset) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO narrative_shot_reference_assets (
                        project_id, episode_number, shot_id, asset_id,
                        asset_version, reference_image_url
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        asset_id = VALUES(asset_id),
                        asset_version = VALUES(asset_version),
                        reference_image_url = VALUES(reference_image_url)
                    """,
                    (
                        asset.project_id,
                        asset.episode_number,
                        asset.shot_id,
                        asset.asset_id,
                        asset.asset_version,
                        asset.reference_image_url,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_episode(
        self, project_id: str, episode_number: int
    ) -> list[ShotReferenceAsset]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT project_id, episode_number, shot_id, asset_id,
                           asset_version, reference_image_url
                    FROM narrative_shot_reference_assets
                    WHERE project_id = %s AND episode_number = %s
                    ORDER BY shot_id ASC
                    """,
                    (project_id, episode_number),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
        return [ShotReferenceAsset(**row) for row in rows]
