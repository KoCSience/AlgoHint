"""Transactional SQLite persistence for potentially large completion-review history."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from algohint.domain.enums import ReviewHistoryKind
from algohint.domain.models import (
    QuizAttempt,
    ReviewHistoryRecord,
    ReviewQuotaStatus,
)
from algohint.domain.ports import ProfileRepository
from algohint.infrastructure.filesystem_paths import DataPaths

DEFAULT_QUOTA_BYTES = 1_073_741_824
DEFAULT_WARNING_RATIO = 0.8
MAX_PAGE_SIZE = 100


class SqliteReviewHistoryRepository:
    """Keep all review records until a predictable per-profile logical quota."""

    def __init__(
        self,
        paths: DataPaths,
        profiles: ProfileRepository,
        *,
        quota_bytes: int = DEFAULT_QUOTA_BYTES,
        warning_ratio: float = DEFAULT_WARNING_RATIO,
    ) -> None:
        if quota_bytes <= 0:
            raise ValueError("quota_bytes must be positive")
        if not 0 < warning_ratio < 1:
            raise ValueError("warning_ratio must be between zero and one")
        self._paths = paths
        self._profiles = profiles
        self._quota_bytes = quota_bytes
        self._warning_bytes = int(quota_bytes * warning_ratio)
        self._paths.review_history_dir.mkdir(parents=True, exist_ok=True)

    def save_quiz_attempt(
        self,
        profile_id: str,
        problem_id: str,
        attempt: QuizAttempt,
    ) -> ReviewQuotaStatus:
        """Insert a detailed snapshot and prune oldest records in one transaction."""

        payload_json = attempt.model_dump_json()
        return self._save(
            profile_id,
            problem_id,
            kind=ReviewHistoryKind.QUIZ_ATTEMPT,
            created_at=attempt.attempted_at.isoformat(),
            payload_json=payload_json,
        )

    def list_records(
        self,
        profile_id: str,
        problem_id: str,
        *,
        kind: str,
        limit: int,
        offset: int,
    ) -> tuple[ReviewHistoryRecord, ...]:
        self._validate_page(limit, offset)
        resolved_kind = ReviewHistoryKind(kind)
        with closing(self._connect(profile_id)) as connection:
            rows = connection.execute(
                """
                SELECT id, problem_id, kind, created_at, payload_json
                FROM history_records
                WHERE problem_id = ? AND kind = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (problem_id, resolved_kind.value, limit, offset),
            ).fetchall()
        return tuple(
            ReviewHistoryRecord(
                record_id=int(row["id"]),
                problem_id=str(row["problem_id"]),
                kind=ReviewHistoryKind(str(row["kind"])),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                payload_json=str(row["payload_json"]),
            )
            for row in rows
        )

    def count_records(self, profile_id: str, problem_id: str, *, kind: str) -> int:
        resolved_kind = ReviewHistoryKind(kind)
        with closing(self._connect(profile_id)) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM history_records
                WHERE problem_id = ? AND kind = ?
                """,
                (problem_id, resolved_kind.value),
            ).fetchone()
        return int(row["count"])

    def quota_status(self, profile_id: str) -> ReviewQuotaStatus:
        with closing(self._connect(profile_id)) as connection:
            used_bytes = self._usage(connection)
        return self._quota_status(used_bytes)

    def _save(
        self,
        profile_id: str,
        problem_id: str,
        *,
        kind: ReviewHistoryKind,
        created_at: str,
        payload_json: str,
    ) -> ReviewQuotaStatus:
        envelope = json.dumps(
            {
                "problem_id": problem_id,
                "kind": kind.value,
                "created_at": created_at,
                "payload": json.loads(payload_json),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        payload_bytes = len(envelope.encode("utf-8"))
        if payload_bytes > self._quota_bytes:
            raise ValueError("1件の復習履歴が保存上限を超えています。")

        with closing(self._connect(profile_id)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO history_records(
                        problem_id, kind, created_at, payload_json, payload_bytes
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        problem_id,
                        kind.value,
                        created_at,
                        payload_json,
                        payload_bytes,
                    ),
                )
                used_bytes = self._usage(connection) + payload_bytes
                self._set_usage(connection, used_bytes)
                used_bytes, pruned_count = self._prune(connection, used_bytes)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self._quota_status(used_bytes, pruned_count=pruned_count)

    def _connect(self, profile_id: str) -> sqlite3.Connection:
        self._profiles.get_profile(profile_id)
        path = self._database_path(profile_id)
        connection = sqlite3.connect(path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        self._initialize(connection)
        return connection

    def _database_path(self, profile_id: str) -> Path:
        # Profile validation above prevents identifiers from escaping this directory.
        return self._paths.review_history_dir / f"{profile_id}.sqlite3"

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS history_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('quiz_attempt', 'code_review')),
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_bytes INTEGER NOT NULL CHECK(payload_bytes > 0)
            );
            CREATE INDEX IF NOT EXISTS history_problem_page
                ON history_records(problem_id, kind, created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS history_oldest
                ON history_records(created_at ASC, id ASC);
            CREATE TABLE IF NOT EXISTS history_meta (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO history_meta(key, value) VALUES ('used_bytes', 0);
            """
        )

    @staticmethod
    def _usage(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT value FROM history_meta WHERE key = 'used_bytes'"
        ).fetchone()
        return int(row["value"])

    @staticmethod
    def _set_usage(connection: sqlite3.Connection, used_bytes: int) -> None:
        connection.execute(
            "UPDATE history_meta SET value = ? WHERE key = 'used_bytes'",
            (used_bytes,),
        )

    def _prune(
        self,
        connection: sqlite3.Connection,
        used_bytes: int,
    ) -> tuple[int, int]:
        pruned_count = 0
        while used_bytes > self._quota_bytes:
            row = connection.execute(
                """
                SELECT id, payload_bytes
                FROM history_records
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                break
            connection.execute(
                "DELETE FROM history_records WHERE id = ?",
                (int(row["id"]),),
            )
            used_bytes -= int(row["payload_bytes"])
            pruned_count += 1
        self._set_usage(connection, used_bytes)
        return used_bytes, pruned_count

    def _quota_status(
        self,
        used_bytes: int,
        *,
        pruned_count: int = 0,
    ) -> ReviewQuotaStatus:
        return ReviewQuotaStatus(
            used_bytes=used_bytes,
            limit_bytes=self._quota_bytes,
            warning=used_bytes >= self._warning_bytes,
            pruned_count=pruned_count,
        )

    @staticmethod
    def _validate_page(limit: int, offset: int) -> None:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if offset < 0:
            raise ValueError("offset must not be negative")
