"""Durable learner-code storage with optimistic drafts and safe result snapshots."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4

from algohint.domain.enums import JudgeStatus, SubmissionMode
from algohint.domain.errors import DraftConflictError
from algohint.domain.models import (
    CodeDraft,
    CodeSnapshot,
    CodeSnapshotSummary,
    PendingProgressUpdate,
    StoredExecutionResult,
)
from algohint.domain.ports import ProfileRepository
from algohint.infrastructure.filesystem_paths import DataPaths

MAX_PAGE_SIZE = 100


class SqliteCodeHistoryRepository:
    """Retain distinct source snapshots until the learner explicitly deletes them.

    Drafts are mutable and revision-checked. Submitted sources are content
    addressed so repeated sample/full runs store the source once while keeping
    the latest learner-visible result for each mode.
    """

    def __init__(self, paths: DataPaths, profiles: ProfileRepository) -> None:
        self._paths = paths
        self._profiles = profiles
        self._initialization_lock = RLock()
        self._initialized_paths: set[Path] = set()
        self._paths.code_history_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._paths.code_history_dir.chmod(0o700)

    def load_draft(self, profile_id: str, problem_id: str) -> CodeDraft:
        with closing(self._connect(profile_id)) as connection:
            row = connection.execute(
                """
                SELECT problem_id, source, revision, updated_at
                FROM drafts WHERE problem_id = ?
                """,
                (problem_id,),
            ).fetchone()
        if row is None:
            return CodeDraft(problem_id=problem_id, source="")
        return CodeDraft(
            problem_id=str(row["problem_id"]),
            source=str(row["source"]),
            revision=int(row["revision"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def save_draft(
        self,
        profile_id: str,
        problem_id: str,
        source: str,
        *,
        expected_revision: int,
    ) -> CodeDraft:
        now = datetime.now(UTC)
        with closing(self._connect(profile_id)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT source, revision, updated_at FROM drafts WHERE problem_id = ?",
                    (problem_id,),
                ).fetchone()
                current_revision = int(row["revision"]) if row is not None else 0
                if current_revision != expected_revision:
                    raise DraftConflictError(current_revision)
                if row is not None and str(row["source"]) == source:
                    connection.commit()
                    return CodeDraft(
                        problem_id=problem_id,
                        source=source,
                        revision=current_revision,
                        updated_at=datetime.fromisoformat(str(row["updated_at"])),
                    )
                next_revision = current_revision + 1
                connection.execute(
                    """
                    INSERT INTO drafts(
                        problem_id, source, source_bytes, revision, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(problem_id) DO UPDATE SET
                        source = excluded.source,
                        source_bytes = excluded.source_bytes,
                        revision = excluded.revision,
                        updated_at = excluded.updated_at
                    """,
                    (
                        problem_id,
                        source,
                        len(source.encode("utf-8")),
                        next_revision,
                        now.isoformat(),
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return CodeDraft(
            problem_id=problem_id,
            source=source,
            revision=next_revision,
            updated_at=now,
        )

    def record_execution(
        self,
        profile_id: str,
        problem_id: str,
        source: str,
        result: StoredExecutionResult,
    ) -> tuple[CodeSnapshot, int]:
        source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        source_bytes = len(source.encode("utf-8"))
        with closing(self._connect(profile_id)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT snapshot_id, source
                    FROM code_snapshots
                    WHERE problem_id = ? AND source_sha256 = ?
                    """,
                    (problem_id, source_sha256),
                ).fetchone()
                if row is None:
                    snapshot_id = uuid4().hex
                    connection.execute(
                        """
                        INSERT INTO code_snapshots(
                            snapshot_id, problem_id, source_sha256, source,
                            source_bytes, first_executed_at, last_executed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot_id,
                            problem_id,
                            source_sha256,
                            source,
                            source_bytes,
                            result.executed_at.isoformat(),
                            result.executed_at.isoformat(),
                        ),
                    )
                else:
                    snapshot_id = str(row["snapshot_id"])
                    # A hash match must never silently replace unrelated source.
                    if str(row["source"]) != source:
                        raise RuntimeError("source hash collision detected")
                    connection.execute(
                        """
                        UPDATE code_snapshots
                        SET last_executed_at = ?
                        WHERE snapshot_id = ?
                        """,
                        (result.executed_at.isoformat(), snapshot_id),
                    )
                connection.execute(
                    """
                    INSERT INTO latest_execution_results(
                        snapshot_id, mode, executed_at, result_json
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(snapshot_id, mode) DO UPDATE SET
                        executed_at = excluded.executed_at,
                        result_json = excluded.result_json
                    """,
                    (
                        snapshot_id,
                        result.mode.value,
                        result.executed_at.isoformat(),
                        result.model_dump_json(),
                    ),
                )
                cursor = connection.execute(
                    """
                    INSERT INTO pending_progress_updates(problem_id, mode, status)
                    VALUES (?, ?, ?)
                    """,
                    (problem_id, result.mode.value, result.status.value),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("progress update insert did not return a sequence")
                sequence = int(cursor.lastrowid)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get_snapshot(profile_id, problem_id, snapshot_id), sequence

    def list_snapshots(
        self,
        profile_id: str,
        problem_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[CodeSnapshotSummary, ...]:
        self._validate_page(limit, offset)
        with closing(self._connect(profile_id)) as connection:
            rows = connection.execute(
                """
                SELECT snapshot_id, problem_id, source_sha256, source_bytes,
                       first_executed_at, last_executed_at
                FROM code_snapshots
                WHERE problem_id = ?
                ORDER BY last_executed_at DESC, snapshot_id DESC
                LIMIT ? OFFSET ?
                """,
                (problem_id, limit, offset),
            ).fetchall()
            return tuple(self._summary(connection, row) for row in rows)

    def count_snapshots(self, profile_id: str, problem_id: str) -> int:
        with closing(self._connect(profile_id)) as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM code_snapshots WHERE problem_id = ?",
                (problem_id,),
            ).fetchone()
        return int(row["count"])

    def get_snapshot(
        self,
        profile_id: str,
        problem_id: str,
        snapshot_id: str,
    ) -> CodeSnapshot:
        with closing(self._connect(profile_id)) as connection:
            row = connection.execute(
                """
                SELECT snapshot_id, problem_id, source_sha256, source, source_bytes,
                       first_executed_at, last_executed_at
                FROM code_snapshots
                WHERE problem_id = ? AND snapshot_id = ?
                """,
                (problem_id, snapshot_id),
            ).fetchone()
            if row is None:
                raise KeyError("Unknown code snapshot")
            summary = self._summary(connection, row)
            return CodeSnapshot(**summary.model_dump(), source=str(row["source"]))

    def delete_snapshot(
        self,
        profile_id: str,
        problem_id: str,
        snapshot_id: str,
    ) -> bool:
        with closing(self._connect(profile_id)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute(
                    """
                    DELETE FROM code_snapshots
                    WHERE problem_id = ? AND snapshot_id = ?
                    """,
                    (problem_id, snapshot_id),
                )
                deleted = cursor.rowcount == 1
                connection.commit()
                if deleted:
                    # secure_delete clears freed cells; truncate prevents source
                    # text from remaining in the reusable WAL after this action.
                    checkpoint = connection.execute(
                        "PRAGMA wal_checkpoint(TRUNCATE)"
                    ).fetchone()
                    if checkpoint is not None and int(checkpoint[0]) != 0:
                        raise RuntimeError("code history WAL checkpoint was busy")
            except Exception:
                connection.rollback()
                raise
        return deleted

    def pending_progress(
        self,
        profile_id: str,
        *,
        after_sequence: int,
    ) -> tuple[PendingProgressUpdate, ...]:
        with closing(self._connect(profile_id)) as connection:
            rows = connection.execute(
                """
                SELECT sequence, problem_id, mode, status
                FROM pending_progress_updates
                WHERE sequence > ?
                ORDER BY sequence ASC
                """,
                (after_sequence,),
            ).fetchall()
        return tuple(
            PendingProgressUpdate(
                sequence=int(row["sequence"]),
                problem_id=str(row["problem_id"]),
                mode=SubmissionMode(str(row["mode"])),
                status=JudgeStatus(str(row["status"])),
            )
            for row in rows
        )

    def acknowledge_progress(self, profile_id: str, *, through_sequence: int) -> None:
        with closing(self._connect(profile_id)) as connection:
            connection.execute(
                "DELETE FROM pending_progress_updates WHERE sequence <= ?",
                (through_sequence,),
            )
            connection.commit()

    def _connect(self, profile_id: str) -> sqlite3.Connection:
        self._profiles.get_profile(profile_id)
        path = self._database_path(profile_id)
        connection = sqlite3.connect(path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        with self._initialization_lock:
            if path not in self._initialized_paths:
                connection.execute("PRAGMA journal_mode = WAL")
                self._initialize(connection)
                path.chmod(0o600)
                self._initialized_paths.add(path)
        return connection

    def _database_path(self, profile_id: str) -> Path:
        # Profile validation prevents identifiers from escaping this directory.
        return self._paths.code_history_dir / f"{profile_id}.sqlite3"

    @staticmethod
    def _initialize(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS drafts (
                problem_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_bytes INTEGER NOT NULL CHECK(
                    source_bytes >= 0 AND source_bytes <= 1048576
                ),
                revision INTEGER NOT NULL CHECK(revision >= 1),
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS code_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                problem_id TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                source TEXT NOT NULL,
                source_bytes INTEGER NOT NULL CHECK(
                    source_bytes >= 0 AND source_bytes <= 1048576
                ),
                first_executed_at TEXT NOT NULL,
                last_executed_at TEXT NOT NULL,
                UNIQUE(problem_id, source_sha256)
            );
            CREATE INDEX IF NOT EXISTS code_snapshot_page
                ON code_snapshots(problem_id, last_executed_at DESC, snapshot_id DESC);
            CREATE TABLE IF NOT EXISTS latest_execution_results (
                snapshot_id TEXT NOT NULL REFERENCES code_snapshots(snapshot_id)
                    ON DELETE CASCADE,
                mode TEXT NOT NULL CHECK(mode IN ('sample', 'full')),
                executed_at TEXT NOT NULL,
                result_json TEXT NOT NULL,
                PRIMARY KEY(snapshot_id, mode)
            );
            CREATE TABLE IF NOT EXISTS pending_progress_updates (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('sample', 'full')),
                status TEXT NOT NULL CHECK(status IN ('AC', 'WA', 'RE', 'TLE', 'CE', 'IE'))
            );
            """
        )
        connection.commit()

    @staticmethod
    def _summary(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> CodeSnapshotSummary:
        results = connection.execute(
            """
            SELECT mode, result_json
            FROM latest_execution_results
            WHERE snapshot_id = ?
            """,
            (str(row["snapshot_id"]),),
        ).fetchall()
        parsed = {
            SubmissionMode(str(result["mode"])): StoredExecutionResult.model_validate_json(
                str(result["result_json"])
            )
            for result in results
        }
        return CodeSnapshotSummary(
            snapshot_id=str(row["snapshot_id"]),
            problem_id=str(row["problem_id"]),
            source_sha256=str(row["source_sha256"]),
            source_bytes=int(row["source_bytes"]),
            first_executed_at=datetime.fromisoformat(str(row["first_executed_at"])),
            last_executed_at=datetime.fromisoformat(str(row["last_executed_at"])),
            sample_result=parsed.get(SubmissionMode.SAMPLE),
            full_result=parsed.get(SubmissionMode.FULL),
        )

    @staticmethod
    def _validate_page(limit: int, offset: int) -> None:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if offset < 0:
            raise ValueError("offset must not be negative")
