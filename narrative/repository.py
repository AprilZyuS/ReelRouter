"""长文本、分集计划与原文分块的持久化接口及实现。"""

import json
from collections.abc import Sequence
from typing import Protocol

import pymysql
from pymysql.cursors import DictCursor

from narrative.schemas import (
    DocumentChunk,
    EpisodePlan,
    EpisodePlanSet,
    EpisodeSummary,
    NarrativeDocument,
    NarrativeProjectProfile,
    ScreenplayCandidate,
    ScreenplayCandidateStatus,
    ScreenplayReview,
    Screenplay,
    PrioritizedStoryboard,
)


class MySQLConnectionSettings(Protocol):
    """叙事模块需要的最小 MySQL 连接配置，避免依赖 video 领域。"""

    host: str
    port: int
    database: str
    user: str
    password: str


class NarrativeKnowledgeRepository(Protocol):
    """文档与分块的存取契约；上层不关心具体存储介质。"""

    def setup(self) -> None:
        """初始化存储所需的表或索引；重复调用必须安全。"""
        ...

    def save_document(
        self,
        document: NarrativeDocument,
        chunks: Sequence[DocumentChunk],
    ) -> None:
        """原子保存一篇原文及其完整分块集合。"""
        ...

    def get_document(self, document_id: str) -> NarrativeDocument | None:
        """按 ID 读取原文；不存在时返回 None。"""
        ...

    def list_chunks(self, document_id: str) -> list[DocumentChunk]:
        """按原文顺序读取全部分块。"""
        ...

    def list_project_chunks(self, project_id: str) -> list[DocumentChunk]:
        """按稳定顺序读取一个项目的全部分块，用于重建项目向量索引。"""
        ...

    def save_project_profile(self, profile: NarrativeProjectProfile) -> None:
        ...

    def get_project_profile(
        self,
        project_id: str,
    ) -> NarrativeProjectProfile | None:
        ...

    def save_episode_plan_set(self, plan_set: EpisodePlanSet) -> None:
        """原子保存项目当前版本的连续分集计划。"""
        ...

    def list_episode_plans(self, project_id: str) -> list[EpisodePlan]:
        """按集号读取项目当前的所有分集计划。"""
        ...

    def save_screenplay(self, screenplay: Screenplay) -> None:
        """保存已通过人工审核的单集剧本。"""
        ...

    def get_screenplay(self, project_id: str, episode_number: int) -> Screenplay | None:
        """读取一集已批准剧本；不存在时返回 None。"""
        ...

    def save_screenplay_candidate(self, candidate: ScreenplayCandidate) -> None:
        """保存候选稿；不得覆盖已批准剧本。"""
        ...

    def get_screenplay_candidate(self, candidate_id: str) -> ScreenplayCandidate | None:
        ...

    def record_screenplay_review(
        self,
        candidate_id: str,
        review: ScreenplayReview,
    ) -> ScreenplayCandidate:
        """记录自动 Reviewer 结论，但不自动批准。"""
        ...

    def approve_screenplay_candidate(self, candidate_id: str) -> ScreenplayCandidate:
        """人工批准通过 Reviewer 的候选稿，并写入剧本和本集摘要。"""
        ...

    def get_episode_summary(
        self,
        project_id: str,
        episode_number: int,
    ) -> EpisodeSummary | None:
        ...

    def save_prioritized_storyboard(self, storyboard: PrioritizedStoryboard) -> None: ...

    def get_prioritized_storyboard(self, project_id: str, episode_number: int) -> PrioritizedStoryboard | None: ...


def _validate_document_chunks(
    document: NarrativeDocument,
    chunks: Sequence[DocumentChunk],
) -> list[DocumentChunk]:
    """在写入前验证分块可完整、精确地回指给定原文。"""
    chunk_list = list(chunks)
    if not chunk_list:
        raise ValueError("保存文档时至少需要一个分块。")

    expected_indexes = list(range(len(chunk_list)))
    actual_indexes = [chunk.chunk_index for chunk in chunk_list]
    if actual_indexes != expected_indexes:
        raise ValueError("chunk_index 必须从 0 开始连续递增。")

    for chunk in chunk_list:
        if chunk.document_id != document.document_id:
            raise ValueError("分块的 document_id 必须与文档一致。")
        if chunk.project_id != document.project_id:
            raise ValueError("分块的 project_id 必须与文档一致。")
        if chunk.content != document.raw_text[chunk.start_char : chunk.end_char]:
            raise ValueError("分块 content 必须精确对应原文的字符位置区间。")

    if chunk_list[0].start_char != 0:
        raise ValueError("第一个分块必须从原文开头开始。")
    if chunk_list[-1].end_char != len(document.raw_text):
        raise ValueError("最后一个分块必须覆盖到原文结尾。")

    for previous, current in zip(chunk_list, chunk_list[1:]):
        if current.start_char > previous.end_char:
            raise ValueError("相邻分块之间不能遗漏原文内容。")
        if current.end_char <= previous.end_char:
            raise ValueError("相邻分块的结束位置必须持续前进。")

    return chunk_list


def _validate_episode_plan_set(
    plan_set: EpisodePlanSet,
    *,
    profile: NarrativeProjectProfile,
    manuscript_chunks: Sequence[DocumentChunk],
) -> list[EpisodePlan]:
    """确保分集计划只引用项目当前小说稿的可追溯分块。"""
    if plan_set.project_id != profile.project_id:
        raise ValueError("EpisodePlanSet 的 project_id 必须与项目 Profile 一致。")

    chunks_by_id = {chunk.chunk_id: chunk for chunk in manuscript_chunks}
    allowed_chunk_ids = set(chunks_by_id)
    if not allowed_chunk_ids:
        raise ValueError("项目当前小说稿没有可供分集计划引用的原文分块。")

    unknown_chunk_ids = sorted(
        {
            chunk_id
            for plan in plan_set.plans
            for chunk_id in plan.source_chunk_ids
            if chunk_id not in allowed_chunk_ids
        }
    )
    if unknown_chunk_ids:
        raise ValueError(
            "EpisodePlanSet 引用了当前小说稿不存在的 source_chunk_ids："
            + ", ".join(unknown_chunk_ids)
        )

    mismatched_chapter_chunks = sorted(
        {
            chunk_id
            for plan in plan_set.plans
            for chunk_id in plan.source_chunk_ids
            if not (
                plan.source_chapter_start
                <= chunks_by_id[chunk_id].chapter_number
                <= plan.source_chapter_end
            )
        }
    )
    if mismatched_chapter_chunks:
        raise ValueError(
            "EpisodePlan 的 source_chapter 范围与 source_chunk_ids 不一致："
            + ", ".join(mismatched_chapter_chunks)
        )

    return list(plan_set.plans)


def _validate_screenplay(
    screenplay: Screenplay,
    *,
    episode_plans: Sequence[EpisodePlan],
    manuscript_chunks: Sequence[DocumentChunk],
) -> None:
    """保证批准剧本仍绑定当前计划、时长和小说知识库证据。"""
    plan = next(
        (
            candidate
            for candidate in episode_plans
            if candidate.episode_number == screenplay.episode_number
        ),
        None,
    )
    if plan is None:
        raise LookupError("剧本对应的 EpisodePlan 不存在，不能保存。")
    if plan.project_id != screenplay.project_id:
        raise ValueError("Screenplay 的 project_id 必须与 EpisodePlan 一致。")
    if plan.target_duration_seconds != screenplay.target_duration_seconds:
        raise ValueError("Screenplay 的目标时长必须与 EpisodePlan 一致。")

    allowed_chunk_ids = {chunk.chunk_id for chunk in manuscript_chunks}
    unknown_chunk_ids = sorted(
        {
            chunk_id
            for scene in screenplay.scenes
            for chunk_id in scene.source_chunk_ids
            if chunk_id not in allowed_chunk_ids
        }
    )
    if unknown_chunk_ids:
        raise ValueError(
            "Screenplay 引用了当前小说稿不存在的 source_chunk_ids："
            + ", ".join(unknown_chunk_ids)
        )

    out_of_scope_chunk_ids = sorted(
        {
            chunk_id
            for scene in screenplay.scenes
            for chunk_id in scene.source_chunk_ids
            if chunk_id not in set(plan.source_chunk_ids)
        }
    )
    if out_of_scope_chunk_ids:
        raise ValueError(
            "Screenplay 只能将 EpisodePlan 的硬证据作为场景出处："
            + ", ".join(out_of_scope_chunk_ids)
        )


class InMemoryNarrativeKnowledgeRepository:
    """用于单元测试与本地开发的内存知识库实现。"""

    def __init__(self) -> None:
        self._documents: dict[str, NarrativeDocument] = {}
        self._chunks: dict[str, list[DocumentChunk]] = {}
        self._project_profiles: dict[str, NarrativeProjectProfile] = {}
        self._episode_plans: dict[str, list[EpisodePlan]] = {}
        self._screenplays: dict[tuple[str, int], Screenplay] = {}
        self._screenplay_candidates: dict[str, ScreenplayCandidate] = {}
        self._episode_summaries: dict[tuple[str, int], EpisodeSummary] = {}
        self._prioritized_storyboards: dict[tuple[str, int], PrioritizedStoryboard] = {}

    def setup(self) -> None:
        """内存实现无需建表，保留该方法以遵守统一接口。"""

    def save_document(
        self,
        document: NarrativeDocument,
        chunks: Sequence[DocumentChunk],
    ) -> None:
        validated_chunks = _validate_document_chunks(document, chunks)
        self._documents[document.document_id] = document
        self._chunks[document.document_id] = validated_chunks

    def get_document(self, document_id: str) -> NarrativeDocument | None:
        return self._documents.get(document_id)

    def list_chunks(self, document_id: str) -> list[DocumentChunk]:
        return list(self._chunks.get(document_id, []))

    def list_project_chunks(self, project_id: str) -> list[DocumentChunk]:
        profile = self.get_project_profile(project_id)
        if profile is not None:
            return self.list_chunks(profile.manuscript_document_id)
        chunks = [
            chunk
            for document_id, document in self._documents.items()
            if document.project_id == project_id
            for chunk in self._chunks[document_id]
        ]
        return sorted(chunks, key=lambda chunk: (chunk.document_id, chunk.chunk_index))

    def save_project_profile(self, profile: NarrativeProjectProfile) -> None:
        """以 project_id 为键保存项目长期叙事状态；同项目新版本覆盖旧版本。"""
        previous = self._project_profiles.get(profile.project_id)
        if (
            previous is not None
            and (
                previous.manuscript_document_id != profile.manuscript_document_id
                or previous.narrative_version != profile.narrative_version
            )
        ):
            self._episode_plans.pop(profile.project_id, None)
            self._screenplays = {
                key: value
                for key, value in self._screenplays.items()
                if key[0] != profile.project_id
            }
            self._screenplay_candidates = {
                key: value
                for key, value in self._screenplay_candidates.items()
                if value.screenplay.project_id != profile.project_id
            }
            self._episode_summaries = {
                key: value
                for key, value in self._episode_summaries.items()
                if key[0] != profile.project_id
            }
            self._prioritized_storyboards = {
                key: value
                for key, value in self._prioritized_storyboards.items()
                if key[0] != profile.project_id
            }
        self._project_profiles[profile.project_id] = profile

    def get_project_profile(
        self,
        project_id: str,
    ) -> NarrativeProjectProfile | None:
        return self._project_profiles.get(project_id)

    def save_episode_plan_set(self, plan_set: EpisodePlanSet) -> None:
        profile = self.get_project_profile(plan_set.project_id)
        if profile is None:
            raise LookupError(
                f"项目 {plan_set.project_id} 不存在 NarrativeProjectProfile。"
            )
        plans = _validate_episode_plan_set(
            plan_set,
            profile=profile,
            manuscript_chunks=self.list_chunks(profile.manuscript_document_id),
        )
        self._episode_plans[plan_set.project_id] = plans

    def list_episode_plans(self, project_id: str) -> list[EpisodePlan]:
        return list(self._episode_plans.get(project_id, []))

    def save_screenplay(self, screenplay: Screenplay) -> None:
        profile = self.get_project_profile(screenplay.project_id)
        if profile is None:
            raise LookupError(
                f"项目 {screenplay.project_id} 不存在 NarrativeProjectProfile。"
            )
        _validate_screenplay(
            screenplay,
            episode_plans=self.list_episode_plans(screenplay.project_id),
            manuscript_chunks=self.list_chunks(profile.manuscript_document_id),
        )
        self._screenplays[(screenplay.project_id, screenplay.episode_number)] = screenplay

    def get_screenplay(self, project_id: str, episode_number: int) -> Screenplay | None:
        return self._screenplays.get((project_id, episode_number))

    def save_screenplay_candidate(self, candidate: ScreenplayCandidate) -> None:
        profile = self.get_project_profile(candidate.screenplay.project_id)
        if profile is None:
            raise LookupError("候选剧本所属项目不存在 NarrativeProjectProfile。")
        _validate_screenplay(
            candidate.screenplay,
            episode_plans=self.list_episode_plans(candidate.screenplay.project_id),
            manuscript_chunks=self.list_chunks(profile.manuscript_document_id),
        )
        self._screenplay_candidates[candidate.candidate_id] = candidate

    def get_screenplay_candidate(self, candidate_id: str) -> ScreenplayCandidate | None:
        return self._screenplay_candidates.get(candidate_id)

    def record_screenplay_review(
        self,
        candidate_id: str,
        review: ScreenplayReview,
    ) -> ScreenplayCandidate:
        candidate = self.get_screenplay_candidate(candidate_id)
        if candidate is None:
            raise LookupError("候选剧本不存在。")
        if candidate.status != ScreenplayCandidateStatus.DRAFT:
            raise ValueError("只有 draft 候选剧本可以记录 Reviewer 结论。")
        updated = candidate.model_copy(
            update={"status": ScreenplayCandidateStatus.REVIEWED, "review": review}
        )
        self._screenplay_candidates[candidate_id] = updated
        return updated

    def approve_screenplay_candidate(self, candidate_id: str) -> ScreenplayCandidate:
        candidate = self.get_screenplay_candidate(candidate_id)
        if candidate is None:
            raise LookupError("候选剧本不存在。")
        if candidate.status != ScreenplayCandidateStatus.REVIEWED or candidate.review is None:
            raise ValueError("候选剧本必须先完成 Reviewer 审查。")
        if not candidate.review.passed:
            raise ValueError("Reviewer 未通过的候选剧本不能批准。")
        self.save_screenplay(candidate.screenplay)
        self._episode_summaries[
            (candidate.screenplay.project_id, candidate.screenplay.episode_number)
        ] = candidate.review.episode_summary
        updated = candidate.model_copy(
            update={"status": ScreenplayCandidateStatus.APPROVED}
        )
        self._screenplay_candidates[candidate_id] = updated
        return updated

    def get_episode_summary(
        self,
        project_id: str,
        episode_number: int,
    ) -> EpisodeSummary | None:
        return self._episode_summaries.get((project_id, episode_number))

    def save_prioritized_storyboard(self, storyboard: PrioritizedStoryboard) -> None:
        if self.get_screenplay(storyboard.project_id, storyboard.episode_number) is None:
            raise LookupError("分镜必须对应一份已批准 Screenplay。")
        self._prioritized_storyboards[(storyboard.project_id, storyboard.episode_number)] = storyboard

    def get_prioritized_storyboard(self, project_id: str, episode_number: int) -> PrioritizedStoryboard | None:
        return self._prioritized_storyboards.get((project_id, episode_number))


class MySQLNarrativeKnowledgeRepository:
    """使用 MySQL 保存原文及可回溯的知识库分块。"""

    def __init__(self, settings: MySQLConnectionSettings) -> None:
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

    def _add_column_if_missing(
        self,
        cursor,
        *,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        """兼容本地既有表，不依赖特定 MySQL 的 IF NOT EXISTS 方言。"""
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
            """,
            (self.settings.database, table_name, column_name),
        )
        if cursor.fetchone() is None:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {definition}")

    def setup(self) -> None:
        """创建叙事文档、分块和项目长期状态表；允许重复初始化。"""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_documents (
                        document_id VARCHAR(64) PRIMARY KEY,
                        project_id VARCHAR(64) NOT NULL,
                        title VARCHAR(200) NOT NULL,
                        source_type VARCHAR(16) NOT NULL,
                        raw_text LONGTEXT NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_narrative_documents_project (project_id)
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_document_chunks (
                        chunk_id VARCHAR(80) PRIMARY KEY,
                        document_id VARCHAR(64) NOT NULL,
                        project_id VARCHAR(64) NOT NULL,
                        chapter_number INT UNSIGNED NOT NULL,
                        chunk_index INT UNSIGNED NOT NULL,
                        content MEDIUMTEXT NOT NULL,
                        start_char INT UNSIGNED NOT NULL,
                        end_char INT UNSIGNED NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT fk_narrative_chunks_document
                            FOREIGN KEY (document_id)
                            REFERENCES narrative_documents(document_id)
                            ON DELETE CASCADE,
                        UNIQUE KEY uq_narrative_chunks_document_index
                            (document_id, chunk_index),
                        INDEX idx_narrative_chunks_project_document
                            (project_id, document_id, chunk_index)
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_project_profiles (
                        project_id VARCHAR(64) PRIMARY KEY,
                        manuscript_document_id VARCHAR(64) NOT NULL,
                        title VARCHAR(120) NOT NULL,
                        logline VARCHAR(300) NOT NULL,
                        style_bible VARCHAR(1000) NOT NULL,
                        planned_episode_count TINYINT UNSIGNED NOT NULL,
                        keywords JSON NOT NULL,
                        genre VARCHAR(80) NOT NULL,
                        episode_duration_seconds TINYINT UNSIGNED NOT NULL,
                        episode_budget_usd DECIMAL(10, 4) NOT NULL,
                        enable_assembly BOOLEAN NOT NULL,
                        narrative_version INT UNSIGNED NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        CONSTRAINT fk_narrative_profiles_document
                            FOREIGN KEY (manuscript_document_id)
                            REFERENCES narrative_documents(document_id)
                            ON DELETE CASCADE
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_episode_plans (
                        project_id VARCHAR(64) NOT NULL,
                        episode_number INT UNSIGNED NOT NULL,
                        title VARCHAR(120) NOT NULL,
                        source_chapter_start INT UNSIGNED NOT NULL,
                        source_chapter_end INT UNSIGNED NOT NULL,
                        target_duration_seconds TINYINT UNSIGNED NOT NULL,
                        episode_goal VARCHAR(500) NOT NULL,
                        closing_hook VARCHAR(500) NOT NULL,
                        source_chunk_ids JSON NOT NULL,
                        scope JSON NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        PRIMARY KEY (project_id, episode_number),
                        CONSTRAINT fk_narrative_episode_plans_profile
                            FOREIGN KEY (project_id)
                            REFERENCES narrative_project_profiles(project_id)
                            ON DELETE CASCADE
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_screenplays (
                        project_id VARCHAR(64) NOT NULL,
                        episode_number INT UNSIGNED NOT NULL,
                        target_duration_seconds TINYINT UNSIGNED NOT NULL,
                        scenes JSON NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        PRIMARY KEY (project_id, episode_number),
                        CONSTRAINT fk_narrative_screenplays_plan
                            FOREIGN KEY (project_id, episode_number)
                            REFERENCES narrative_episode_plans(project_id, episode_number)
                            ON DELETE CASCADE
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_screenplay_candidates (
                        candidate_id VARCHAR(64) PRIMARY KEY,
                        project_id VARCHAR(64) NOT NULL,
                        episode_number INT UNSIGNED NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        screenplay JSON NOT NULL,
                        review JSON NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        CONSTRAINT fk_narrative_candidates_plan
                            FOREIGN KEY (project_id, episode_number)
                            REFERENCES narrative_episode_plans(project_id, episode_number)
                            ON DELETE CASCADE,
                        INDEX idx_narrative_candidates_episode
                            (project_id, episode_number, updated_at)
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_episode_summaries (
                        project_id VARCHAR(64) NOT NULL,
                        episode_number INT UNSIGNED NOT NULL,
                        recap TEXT NOT NULL,
                        unresolved_loops JSON NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (project_id, episode_number),
                        CONSTRAINT fk_narrative_summaries_plan
                            FOREIGN KEY (project_id, episode_number)
                            REFERENCES narrative_episode_plans(project_id, episode_number)
                            ON DELETE CASCADE
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS narrative_prioritized_storyboards (
                        project_id VARCHAR(64) NOT NULL,
                        episode_number INT UNSIGNED NOT NULL,
                        target_duration_seconds TINYINT UNSIGNED NOT NULL,
                        shots JSON NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                            ON UPDATE CURRENT_TIMESTAMP,
                        PRIMARY KEY (project_id, episode_number),
                        CONSTRAINT fk_narrative_prioritized_storyboards_screenplay
                            FOREIGN KEY (project_id, episode_number)
                            REFERENCES narrative_screenplays(project_id, episode_number)
                            ON DELETE CASCADE
                    ) ENGINE=InnoDB
                      DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                    """
                )

                # 兼容已创建的本地开发表。先查 information_schema 再 ALTER，
                # 避免依赖 MySQL 版本相关的 ADD COLUMN IF NOT EXISTS 语法。
                for table_name, column_name, definition in (
                    ("narrative_project_profiles", "keywords", "keywords JSON NULL"),
                    ("narrative_project_profiles", "genre", "genre VARCHAR(80) NOT NULL DEFAULT '未指定'"),
                    ("narrative_project_profiles", "episode_duration_seconds", "episode_duration_seconds TINYINT UNSIGNED NOT NULL DEFAULT 45"),
                    ("narrative_project_profiles", "episode_budget_usd", "episode_budget_usd DECIMAL(10, 4) NOT NULL DEFAULT 1.0000"),
                    ("narrative_project_profiles", "enable_assembly", "enable_assembly BOOLEAN NOT NULL DEFAULT TRUE"),
                    ("narrative_project_profiles", "narrative_version", "narrative_version INT UNSIGNED NOT NULL DEFAULT 1"),
                    ("narrative_episode_plans", "scope", "scope JSON NULL"),
                ):
                    self._add_column_if_missing(
                        cursor,
                        table_name=table_name,
                        column_name=column_name,
                        definition=definition,
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_document(
        self,
        document: NarrativeDocument,
        chunks: Sequence[DocumentChunk],
    ) -> None:
        """事务内更新原文，并以新分块集合完整替换旧集合。"""
        validated_chunks = _validate_document_chunks(document, chunks)
        connection = self._connect()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO narrative_documents (
                        document_id, project_id, title, source_type, raw_text
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        project_id = VALUES(project_id),
                        title = VALUES(title),
                        source_type = VALUES(source_type),
                        raw_text = VALUES(raw_text)
                    """,
                    (
                        document.document_id,
                        document.project_id,
                        document.title,
                        document.source_type,
                        document.raw_text,
                    ),
                )
                cursor.execute(
                    "DELETE FROM narrative_document_chunks WHERE document_id = %s",
                    (document.document_id,),
                )
                cursor.executemany(
                    """
                    INSERT INTO narrative_document_chunks (
                        chunk_id,
                        document_id,
                        project_id,
                        chapter_number,
                        chunk_index,
                        content,
                        start_char,
                        end_char
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            chunk.chunk_id,
                            chunk.document_id,
                            chunk.project_id,
                            chunk.chapter_number,
                            chunk.chunk_index,
                            chunk.content,
                            chunk.start_char,
                            chunk.end_char,
                        )
                        for chunk in validated_chunks
                    ],
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_document(self, document_id: str) -> NarrativeDocument | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT document_id, project_id, title, source_type, raw_text
                    FROM narrative_documents
                    WHERE document_id = %s
                    """,
                    (document_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()

        if row is None:
            return None
        return NarrativeDocument(**row)

    def list_chunks(self, document_id: str) -> list[DocumentChunk]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        chunk_id,
                        document_id,
                        project_id,
                        chapter_number,
                        chunk_index,
                        content,
                        start_char,
                        end_char
                    FROM narrative_document_chunks
                    WHERE document_id = %s
                    ORDER BY chunk_index ASC
                    """,
                    (document_id,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        return [DocumentChunk(**row) for row in rows]

    def list_project_chunks(self, project_id: str) -> list[DocumentChunk]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT manuscript_document_id
                    FROM narrative_project_profiles
                    WHERE project_id = %s
                    """,
                    (project_id,),
                )
                profile_row = cursor.fetchone()
                if profile_row is not None:
                    cursor.execute(
                        """
                        SELECT
                            chunk_id, document_id, project_id, chapter_number,
                            chunk_index, content, start_char, end_char
                        FROM narrative_document_chunks
                        WHERE document_id = %s
                        ORDER BY chunk_index ASC
                        """,
                        (profile_row["manuscript_document_id"],),
                    )
                    rows = cursor.fetchall()
                    return [DocumentChunk(**row) for row in rows]
                cursor.execute(
                    """
                    SELECT
                        chunk_id,
                        document_id,
                        project_id,
                        chapter_number,
                        chunk_index,
                        content,
                        start_char,
                        end_char
                    FROM narrative_document_chunks
                    WHERE project_id = %s
                    ORDER BY document_id ASC, chunk_index ASC
                    """,
                    (project_id,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        return [DocumentChunk(**row) for row in rows]

    def save_project_profile(self, profile: NarrativeProjectProfile) -> None:
        """发布当前小说版本，并使旧版本派生资产整体失效。"""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT manuscript_document_id, narrative_version
                    FROM narrative_project_profiles
                    WHERE project_id = %s
                    FOR UPDATE
                    """,
                    (profile.project_id,),
                )
                previous = cursor.fetchone()
                if previous is not None and (
                    previous["manuscript_document_id"]
                    != profile.manuscript_document_id
                    or int(previous["narrative_version"])
                    != profile.narrative_version
                ):
                    # 计划是所有下游叙事资产的根外键；删除计划会级联删除
                    # 已批准剧本、候选稿和摘要，分镜表再显式清理。
                    cursor.execute(
                        "DELETE FROM narrative_prioritized_storyboards WHERE project_id = %s",
                        (profile.project_id,),
                    )
                    cursor.execute(
                        "DELETE FROM narrative_episode_plans WHERE project_id = %s",
                        (profile.project_id,),
                    )
                cursor.execute(
                    """
                    INSERT INTO narrative_project_profiles (
                        project_id,
                        manuscript_document_id,
                        title,
                        logline,
                        style_bible,
                        planned_episode_count,
                        keywords,
                        genre,
                        episode_duration_seconds,
                        episode_budget_usd,
                        enable_assembly,
                        narrative_version
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        manuscript_document_id = VALUES(manuscript_document_id),
                        title = VALUES(title),
                        logline = VALUES(logline),
                        style_bible = VALUES(style_bible),
                        planned_episode_count = VALUES(planned_episode_count),
                        keywords = VALUES(keywords),
                        genre = VALUES(genre),
                        episode_duration_seconds = VALUES(episode_duration_seconds),
                        episode_budget_usd = VALUES(episode_budget_usd),
                        enable_assembly = VALUES(enable_assembly),
                        narrative_version = VALUES(narrative_version)
                    """,
                    (
                        profile.project_id,
                        profile.manuscript_document_id,
                        profile.title,
                        profile.logline,
                        profile.style_bible,
                        profile.planned_episode_count,
                        json.dumps(profile.keywords, ensure_ascii=False),
                        profile.genre,
                        profile.episode_duration_seconds,
                        profile.episode_budget_usd,
                        profile.enable_assembly,
                        profile.narrative_version,
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_project_profile(
        self,
        project_id: str,
    ) -> NarrativeProjectProfile | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        project_id,
                        manuscript_document_id,
                        title,
                        logline,
                        style_bible,
                        planned_episode_count,
                        keywords,
                        genre,
                        episode_duration_seconds,
                        episode_budget_usd,
                        enable_assembly,
                        narrative_version
                    FROM narrative_project_profiles
                    WHERE project_id = %s
                    """,
                    (project_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()

        if row is None:
            return None
        raw_keywords = row.get("keywords")
        row["keywords"] = (
            json.loads(raw_keywords)
            if isinstance(raw_keywords, str)
            else raw_keywords or []
        )
        row["episode_budget_usd"] = float(row["episode_budget_usd"])
        row["enable_assembly"] = bool(row["enable_assembly"])
        return NarrativeProjectProfile(**row)

    def save_episode_plan_set(self, plan_set: EpisodePlanSet) -> None:
        """事务内替换项目当前计划，避免留下新旧两版混合的分集序列。"""
        profile = self.get_project_profile(plan_set.project_id)
        if profile is None:
            raise LookupError(
                f"项目 {plan_set.project_id} 不存在 NarrativeProjectProfile。"
            )
        plans = _validate_episode_plan_set(
            plan_set,
            profile=profile,
            manuscript_chunks=self.list_chunks(profile.manuscript_document_id),
        )

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM narrative_episode_plans WHERE project_id = %s",
                    (plan_set.project_id,),
                )
                cursor.executemany(
                    """
                    INSERT INTO narrative_episode_plans (
                        project_id,
                        episode_number,
                        title,
                        source_chapter_start,
                        source_chapter_end,
                        target_duration_seconds,
                        episode_goal,
                        closing_hook,
                        source_chunk_ids,
                        scope
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            plan.project_id,
                            plan.episode_number,
                            plan.title,
                            plan.source_chapter_start,
                            plan.source_chapter_end,
                            plan.target_duration_seconds,
                            plan.episode_goal,
                            plan.closing_hook,
                            json.dumps(plan.source_chunk_ids, ensure_ascii=False),
                            (
                                json.dumps(plan.scope.model_dump(), ensure_ascii=False)
                                if plan.scope is not None
                                else None
                            ),
                        )
                        for plan in plans
                    ],
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_episode_plans(self, project_id: str) -> list[EpisodePlan]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        project_id,
                        episode_number,
                        title,
                        source_chapter_start,
                        source_chapter_end,
                        target_duration_seconds,
                        episode_goal,
                        closing_hook,
                        source_chunk_ids,
                        scope
                    FROM narrative_episode_plans
                    WHERE project_id = %s
                    ORDER BY episode_number ASC
                    """,
                    (project_id,),
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        plans: list[EpisodePlan] = []
        for row in rows:
            raw_chunk_ids = row["source_chunk_ids"]
            row["source_chunk_ids"] = (
                json.loads(raw_chunk_ids)
                if isinstance(raw_chunk_ids, str)
                else raw_chunk_ids
            )
            raw_scope = row.get("scope")
            row["scope"] = (
                json.loads(raw_scope)
                if isinstance(raw_scope, str)
                else raw_scope
            )
            plans.append(EpisodePlan(**row))
        return plans

    def save_screenplay(self, screenplay: Screenplay) -> None:
        """以 (project_id, episode_number) 覆盖保存一份已批准剧本。"""
        profile = self.get_project_profile(screenplay.project_id)
        if profile is None:
            raise LookupError(
                f"项目 {screenplay.project_id} 不存在 NarrativeProjectProfile。"
            )
        _validate_screenplay(
            screenplay,
            episode_plans=self.list_episode_plans(screenplay.project_id),
            manuscript_chunks=self.list_chunks(profile.manuscript_document_id),
        )

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO narrative_screenplays (
                        project_id, episode_number, target_duration_seconds, scenes
                    )
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        target_duration_seconds = VALUES(target_duration_seconds),
                        scenes = VALUES(scenes)
                    """,
                    (
                        screenplay.project_id,
                        screenplay.episode_number,
                        screenplay.target_duration_seconds,
                        json.dumps(
                            [scene.model_dump() for scene in screenplay.scenes],
                            ensure_ascii=False,
                        ),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_screenplay(self, project_id: str, episode_number: int) -> Screenplay | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT project_id, episode_number, target_duration_seconds, scenes
                    FROM narrative_screenplays
                    WHERE project_id = %s AND episode_number = %s
                    """,
                    (project_id, episode_number),
                )
                row = cursor.fetchone()
        finally:
            connection.close()

        if row is None:
            return None
        raw_scenes = row["scenes"]
        row["scenes"] = json.loads(raw_scenes) if isinstance(raw_scenes, str) else raw_scenes
        return Screenplay(**row)

    def save_screenplay_candidate(self, candidate: ScreenplayCandidate) -> None:
        """保存候选稿；这不会修改已批准剧本或上一集长期记忆。"""
        profile = self.get_project_profile(candidate.screenplay.project_id)
        if profile is None:
            raise LookupError("候选剧本所属项目不存在 NarrativeProjectProfile。")
        _validate_screenplay(
            candidate.screenplay,
            episode_plans=self.list_episode_plans(candidate.screenplay.project_id),
            manuscript_chunks=self.list_chunks(profile.manuscript_document_id),
        )
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO narrative_screenplay_candidates (
                        candidate_id, project_id, episode_number, status, screenplay, review
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        status = VALUES(status),
                        screenplay = VALUES(screenplay),
                        review = VALUES(review)
                    """,
                    (
                        candidate.candidate_id,
                        candidate.screenplay.project_id,
                        candidate.screenplay.episode_number,
                        candidate.status.value,
                        json.dumps(candidate.screenplay.model_dump(), ensure_ascii=False),
                        (
                            json.dumps(candidate.review.model_dump(), ensure_ascii=False)
                            if candidate.review is not None
                            else None
                        ),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_screenplay_candidate(self, candidate_id: str) -> ScreenplayCandidate | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT candidate_id, status, screenplay, review
                    FROM narrative_screenplay_candidates
                    WHERE candidate_id = %s
                    """,
                    (candidate_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        screenplay = row["screenplay"]
        review = row["review"]
        return ScreenplayCandidate(
            candidate_id=row["candidate_id"],
            status=ScreenplayCandidateStatus(row["status"]),
            screenplay=Screenplay(**(json.loads(screenplay) if isinstance(screenplay, str) else screenplay)),
            review=(
                ScreenplayReview(**(json.loads(review) if isinstance(review, str) else review))
                if review is not None
                else None
            ),
        )

    def record_screenplay_review(
        self,
        candidate_id: str,
        review: ScreenplayReview,
    ) -> ScreenplayCandidate:
        candidate = self.get_screenplay_candidate(candidate_id)
        if candidate is None:
            raise LookupError("候选剧本不存在。")
        if candidate.status != ScreenplayCandidateStatus.DRAFT:
            raise ValueError("只有 draft 候选剧本可以记录 Reviewer 结论。")
        updated = candidate.model_copy(
            update={"status": ScreenplayCandidateStatus.REVIEWED, "review": review}
        )
        self.save_screenplay_candidate(updated)
        return updated

    def approve_screenplay_candidate(self, candidate_id: str) -> ScreenplayCandidate:
        """在一个 MySQL 事务中发布剧本及其跨集摘要。"""
        candidate = self.get_screenplay_candidate(candidate_id)
        if candidate is None:
            raise LookupError("候选剧本不存在。")
        if candidate.status != ScreenplayCandidateStatus.REVIEWED or candidate.review is None:
            raise ValueError("候选剧本必须先完成 Reviewer 审查。")
        if not candidate.review.passed or candidate.review.episode_summary is None:
            raise ValueError("Reviewer 未通过的候选剧本不能批准。")

        profile = self.get_project_profile(candidate.screenplay.project_id)
        if profile is None:
            raise LookupError("候选剧本所属项目不存在 NarrativeProjectProfile。")
        _validate_screenplay(
            candidate.screenplay,
            episode_plans=self.list_episode_plans(candidate.screenplay.project_id),
            manuscript_chunks=self.list_chunks(profile.manuscript_document_id),
        )

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO narrative_screenplays (
                        project_id, episode_number, target_duration_seconds, scenes
                    ) VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        target_duration_seconds = VALUES(target_duration_seconds),
                        scenes = VALUES(scenes)
                    """,
                    (
                        candidate.screenplay.project_id,
                        candidate.screenplay.episode_number,
                        candidate.screenplay.target_duration_seconds,
                        json.dumps(
                            [scene.model_dump() for scene in candidate.screenplay.scenes],
                            ensure_ascii=False,
                        ),
                    ),
                )
                summary = candidate.review.episode_summary
                cursor.execute(
                    """
                    INSERT INTO narrative_episode_summaries (
                        project_id, episode_number, recap, unresolved_loops
                    ) VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        recap = VALUES(recap),
                        unresolved_loops = VALUES(unresolved_loops)
                    """,
                    (
                        candidate.screenplay.project_id,
                        candidate.screenplay.episode_number,
                        summary.recap,
                        json.dumps(summary.unresolved_loops, ensure_ascii=False),
                    ),
                )
                cursor.execute(
                    """
                    UPDATE narrative_screenplay_candidates
                    SET status = %s
                    WHERE candidate_id = %s
                    """,
                    (ScreenplayCandidateStatus.APPROVED.value, candidate_id),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        approved = candidate.model_copy(
            update={"status": ScreenplayCandidateStatus.APPROVED}
        )
        return approved

    def get_episode_summary(
        self,
        project_id: str,
        episode_number: int,
    ) -> EpisodeSummary | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT episode_number, recap, unresolved_loops
                    FROM narrative_episode_summaries
                    WHERE project_id = %s AND episode_number = %s
                    """,
                    (project_id, episode_number),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        unresolved_loops = row["unresolved_loops"]
        return EpisodeSummary(
            episode_number=int(row["episode_number"]),
            recap=row["recap"],
            unresolved_loops=(
                json.loads(unresolved_loops)
                if isinstance(unresolved_loops, str)
                else unresolved_loops
            ),
        )

    def save_prioritized_storyboard(self, storyboard: PrioritizedStoryboard) -> None:
        if self.get_screenplay(storyboard.project_id, storyboard.episode_number) is None:
            raise LookupError("分镜必须对应一份已批准 Screenplay。")
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO narrative_prioritized_storyboards (
                        project_id, episode_number, target_duration_seconds, shots
                    ) VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        target_duration_seconds = VALUES(target_duration_seconds),
                        shots = VALUES(shots)
                    """,
                    (
                        storyboard.project_id,
                        storyboard.episode_number,
                        storyboard.target_duration_seconds,
                        json.dumps(
                            [shot.model_dump() for shot in storyboard.shots],
                            ensure_ascii=False,
                        ),
                    ),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_prioritized_storyboard(
        self,
        project_id: str,
        episode_number: int,
    ) -> PrioritizedStoryboard | None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT project_id, episode_number, target_duration_seconds, shots
                    FROM narrative_prioritized_storyboards
                    WHERE project_id = %s AND episode_number = %s
                    """,
                    (project_id, episode_number),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        raw_shots = row["shots"]
        row["shots"] = json.loads(raw_shots) if isinstance(raw_shots, str) else raw_shots
        return PrioritizedStoryboard(**row)
