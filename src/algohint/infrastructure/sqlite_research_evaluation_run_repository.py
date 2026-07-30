"""Bounded SQLite evidence store for live fixed-case Research evaluation."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any, Literal, cast

from algohint.domain.models import (
    ResearchEvaluationCase,
    ResearchEvaluationRun,
    ResearchResult,
)
from algohint.infrastructure.filesystem_paths import DataPaths

MAX_EVALUATION_BYTES = 64 * 1024 * 1024


class SqliteResearchEvaluationRunRepository:
    """Preserve final public-case results without Exa highlights or credentials."""

    def __init__(self, paths: DataPaths) -> None:
        self._path = paths.research_evaluation_runs_file

    def save(
        self,
        case: ResearchEvaluationCase,
        result: ResearchResult,
    ) -> ResearchEvaluationRun:
        """Append one immutable run so later reports remain evidence-backed."""

        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._path.parent.chmod(0o700)
        payload_json = result.model_dump_json()
        created_at = datetime.now(UTC)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO research_evaluation_runs (
                    case_id, problem_id, judge_status, created_at,
                    payload_json, payload_bytes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.problem_id,
                    case.judge_status,
                    created_at.isoformat(),
                    payload_json,
                    len(payload_json.encode("utf-8")),
                ),
            )
            connection.commit()
            self._prune(connection)
            if cursor.lastrowid is None:
                raise RuntimeError("evaluation run insert did not return an ID")
            row = connection.execute(
                """
                SELECT id, case_id, problem_id, judge_status, created_at, payload_json
                FROM research_evaluation_runs
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        if row is None:
            raise RuntimeError("saved evaluation run is unavailable")
        return self._entry(row)

    def list_latest(self) -> tuple[ResearchEvaluationRun, ...]:
        """Return only the newest result per fixed case for comparable reports."""

        if not self._path.exists():
            return ()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT run.id, run.case_id, run.problem_id, run.judge_status,
                       run.created_at, run.payload_json
                FROM research_evaluation_runs AS run
                INNER JOIN (
                    SELECT case_id, MAX(id) AS latest_id
                    FROM research_evaluation_runs
                    GROUP BY case_id
                ) AS latest ON latest.latest_id = run.id
                ORDER BY run.case_id
                """
            ).fetchall()
        return tuple(self._entry(row) for row in rows)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_evaluation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                problem_id TEXT NOT NULL,
                judge_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_bytes INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS evaluation_case_id "
            "ON research_evaluation_runs(case_id, id DESC)"
        )
        connection.commit()
        self._path.chmod(0o600)
        return connection

    @staticmethod
    def _prune(connection: sqlite3.Connection) -> None:
        """Bound logical payload size while retaining recent append-only evidence."""

        used_bytes = int(
            connection.execute(
                """
                SELECT COALESCE(SUM(payload_bytes), 0)
                FROM research_evaluation_runs
                """
            ).fetchone()[0]
        )
        while used_bytes > MAX_EVALUATION_BYTES:
            cursor = connection.execute(
                """
                DELETE FROM research_evaluation_runs
                WHERE id IN (
                    SELECT id FROM research_evaluation_runs
                    ORDER BY id ASC LIMIT 20
                )
                """
            )
            connection.commit()
            if cursor.rowcount == 0:
                raise RuntimeError("evaluation run quota cannot be reduced")
            used_bytes = int(
                connection.execute(
                    """
                    SELECT COALESCE(SUM(payload_bytes), 0)
                    FROM research_evaluation_runs
                    """
                ).fetchone()[0]
            )

    @staticmethod
    def _entry(row: tuple[Any, ...]) -> ResearchEvaluationRun:
        return ResearchEvaluationRun(
            entry_id=int(row[0]),
            case_id=str(row[1]),
            problem_id=str(row[2]),
            judge_status=cast(Literal["WA", "TLE", "AC"], str(row[3])),
            created_at=datetime.fromisoformat(str(row[4])),
            result=ResearchResult.model_validate_json(str(row[5])),
        )
