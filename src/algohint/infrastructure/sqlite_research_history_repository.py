"""Bounded profile-scoped SQLite history for grounded research responses."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from algohint.domain.models import ResearchHistoryEntry, ResearchResult
from algohint.domain.ports import ProfileRepository
from algohint.infrastructure.filesystem_paths import DataPaths

MAX_PROFILE_BYTES = 64 * 1024 * 1024


class SqliteResearchHistoryRepository:
    """Persist final citations and trace while excluding raw retrieved contents."""

    def __init__(self, paths: DataPaths, profiles: ProfileRepository) -> None:
        self._paths = paths
        self._profiles = profiles
        self._paths.research_history_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        profile_id: str,
        problem_id: str,
        judge_status: str,
        result: ResearchResult,
    ) -> ResearchHistoryEntry:
        self._profiles.get_profile(profile_id)
        path = self._path(profile_id)
        payload_json = result.model_dump_json()
        with self._connect(path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO research_history (
                    problem_id, judge_status, created_at, payload_json, payload_bytes
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    problem_id,
                    judge_status,
                    datetime.now(UTC).isoformat(),
                    payload_json,
                    len(payload_json.encode("utf-8")),
                ),
            )
            connection.commit()
            self._prune(connection)
            if cursor.lastrowid is None:
                raise RuntimeError("research history insert did not return an ID")
            row_id = cursor.lastrowid
            row = connection.execute(
                """
                SELECT id, problem_id, judge_status, created_at, payload_json
                FROM research_history WHERE id = ?
                """,
                (row_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("saved research history row is unavailable")
        return self._entry(profile_id, row)

    def list(
        self,
        profile_id: str,
        problem_id: str,
        *,
        limit: int = 10,
    ) -> tuple[ResearchHistoryEntry, ...]:
        self._profiles.get_profile(profile_id)
        if not 1 <= limit <= 100:
            raise ValueError("research history limit must be between 1 and 100")
        path = self._path(profile_id)
        if not path.exists():
            return ()
        with self._connect(path) as connection:
            rows = connection.execute(
                """
                SELECT id, problem_id, judge_status, created_at, payload_json
                FROM research_history
                WHERE problem_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (problem_id, limit),
            ).fetchall()
        return tuple(self._entry(profile_id, row) for row in rows)

    def _path(self, profile_id: str):
        return self._paths.research_history_dir / f"{profile_id}.sqlite3"

    @staticmethod
    def _connect(path) -> sqlite3.Connection:
        connection = sqlite3.connect(path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id TEXT NOT NULL,
                judge_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_bytes INTEGER NOT NULL
            )
            """
        )
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(research_history)")
        }
        if "payload_bytes" not in columns:
            connection.execute(
                "ALTER TABLE research_history ADD COLUMN payload_bytes INTEGER NOT NULL DEFAULT 0"
            )
            connection.execute(
                "UPDATE research_history SET payload_bytes = length(CAST(payload_json AS BLOB))"
            )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS research_problem_id "
            "ON research_history(problem_id, id DESC)"
        )
        connection.commit()
        path.chmod(0o600)
        return connection

    @staticmethod
    def _prune(connection: sqlite3.Connection) -> None:
        """Keep the logical database below quota without deleting the DB file."""

        used_bytes = int(
            connection.execute(
                "SELECT COALESCE(SUM(payload_bytes), 0) FROM research_history"
            ).fetchone()[0]
        )
        while used_bytes > MAX_PROFILE_BYTES:
            cursor = connection.execute(
                """
                DELETE FROM research_history WHERE id IN (
                    SELECT id FROM research_history ORDER BY id ASC LIMIT 20
                )
                """
            )
            connection.commit()
            if cursor.rowcount == 0:
                raise RuntimeError("research history quota cannot be reduced")
            used_bytes = int(
                connection.execute(
                    "SELECT COALESCE(SUM(payload_bytes), 0) FROM research_history"
                ).fetchone()[0]
            )

    @staticmethod
    def _entry(
        profile_id: str,
        row: tuple[Any, ...],
    ) -> ResearchHistoryEntry:
        return ResearchHistoryEntry(
            entry_id=int(row[0]),
            profile_id=profile_id,
            problem_id=str(row[1]),
            judge_status=str(row[2]),
            created_at=datetime.fromisoformat(str(row[3])),
            result=ResearchResult.model_validate(json.loads(str(row[4]))),
        )
