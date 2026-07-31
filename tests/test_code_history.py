"""Code history tests cover persistence, deduplication, conflicts, and deletion."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from algohint.application.code_workspace_service import CodeWorkspaceService
from algohint.application.profile_service import ProfileService
from algohint.application.submission_service import SubmissionService
from algohint.domain.enums import JudgeStatus, SubmissionMode
from algohint.domain.errors import DraftConflictError
from algohint.domain.models import StoredExecutionResult
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.local_judge_runner import LocalJudgeRunner
from algohint.infrastructure.sqlite_code_history_repository import (
    SqliteCodeHistoryRepository,
)

DATA_DIR = Path(__file__).parents[1] / "data"
CORRECT_SOURCE = "a, b = map(int, input().split())\nprint(a + b)"


def make_services(tmp_path: Path):
    runtime_paths = DataPaths(tmp_path / "runtime-data")
    profiles = JsonProfileRepository(runtime_paths)
    logs = JsonLearningLogRepository(runtime_paths, profiles)
    profile = ProfileService(profiles, logs).create_profile("履歴テスト")
    history = SqliteCodeHistoryRepository(runtime_paths, profiles)
    workspace = CodeWorkspaceService(history)
    submissions = SubmissionService(
        JsonProblemRepository(DataPaths(DATA_DIR)),
        logs,
        LocalJudgeRunner(),
        history,
    )
    return runtime_paths, profile, logs, history, workspace, submissions


def stored_result(mode: SubmissionMode, status: JudgeStatus) -> StoredExecutionResult:
    return StoredExecutionResult(
        mode=mode,
        executed_at=datetime.now(UTC),
        status=status,
        passed_count=1 if status is JudgeStatus.AC else 0,
        total_count=1,
        elapsed_ms=1,
        message="安全化済み結果",
    )


def test_draft_survives_repository_restart_and_unchanged_save(tmp_path: Path) -> None:
    paths, profile, _, _, workspace, _ = make_services(tmp_path)

    saved = workspace.save_draft(
        profile.profile_id,
        "l0_two_values",
        CORRECT_SOURCE,
        expected_revision=0,
    )
    unchanged = workspace.save_draft(
        profile.profile_id,
        "l0_two_values",
        CORRECT_SOURCE,
        expected_revision=saved.revision,
    )
    restored = CodeWorkspaceService(
        SqliteCodeHistoryRepository(paths, JsonProfileRepository(paths))
    ).load_draft(profile.profile_id, "l0_two_values")

    assert saved.revision == unchanged.revision == restored.revision == 1
    assert restored.source == CORRECT_SOURCE


def test_stale_draft_revision_cannot_overwrite_newer_tab(tmp_path: Path) -> None:
    _, profile, _, _, workspace, _ = make_services(tmp_path)
    first = workspace.save_draft(
        profile.profile_id,
        "l0_two_values",
        "print('first')",
        expected_revision=0,
    )
    workspace.save_draft(
        profile.profile_id,
        "l0_two_values",
        "print('newer tab')",
        expected_revision=first.revision,
    )

    with pytest.raises(DraftConflictError) as captured:
        workspace.save_draft(
            profile.profile_id,
            "l0_two_values",
            "print('stale tab')",
            expected_revision=first.revision,
        )

    assert captured.value.current_revision == 2


def test_source_limit_is_measured_as_utf8_bytes(tmp_path: Path) -> None:
    _, profile, _, _, workspace, _ = make_services(tmp_path)
    exact = "あ" * (1_048_575 // 3)
    workspace.save_draft(
        profile.profile_id,
        "l0_two_values",
        exact,
        expected_revision=0,
    )

    with pytest.raises(ValueError, match="1 MiB"):
        workspace.save_draft(
            profile.profile_id,
            "l0_two_values",
            exact + "あ",
            expected_revision=1,
        )


def test_same_source_keeps_latest_result_per_mode(tmp_path: Path) -> None:
    _, profile, _, history, _, _ = make_services(tmp_path)
    first, _ = history.record_execution(
        profile.profile_id,
        "l0_two_values",
        CORRECT_SOURCE,
        stored_result(SubmissionMode.SAMPLE, JudgeStatus.AC),
    )
    second, _ = history.record_execution(
        profile.profile_id,
        "l0_two_values",
        CORRECT_SOURCE,
        stored_result(SubmissionMode.FULL, JudgeStatus.WA),
    )
    latest, _ = history.record_execution(
        profile.profile_id,
        "l0_two_values",
        CORRECT_SOURCE,
        stored_result(SubmissionMode.FULL, JudgeStatus.AC),
    )

    assert first.snapshot_id == second.snapshot_id == latest.snapshot_id
    assert history.count_snapshots(profile.profile_id, "l0_two_values") == 1
    assert latest.sample_result is not None
    assert latest.sample_result.status is JudgeStatus.AC
    assert latest.full_result is not None
    assert latest.full_result.status is JudgeStatus.AC


def test_submission_persists_only_learner_safe_hidden_result(tmp_path: Path) -> None:
    _, profile, logs, history, _, submissions = make_services(tmp_path)
    hidden_failure = (
        "a, b = map(int, input().split())\n"
        "if a == 0:\n"
        "    raise RuntimeError(f'hidden values: {a} {b}')\n"
        "print(a + b)\n"
    )

    result = submissions.submit(profile.profile_id, "l0_two_values", hidden_failure)
    snapshot = history.list_snapshots(
        profile.profile_id,
        "l0_two_values",
        limit=20,
        offset=0,
    )[0]
    database_bytes = (
        DataPaths(tmp_path / "runtime-data")
        .code_history_dir.joinpath(f"{profile.profile_id}.sqlite3")
        .read_bytes()
    )

    assert result.status is JudgeStatus.RE
    assert snapshot.full_result is not None
    assert snapshot.full_result.diagnostic is not None
    assert snapshot.full_result.diagnostic.redacted
    assert snapshot.full_result.diagnostic.details is None
    assert b"hidden values: 0" not in database_bytes
    assert logs.load_log(profile.profile_id).progress["l0_two_values"].attempt_count == 1


def test_progress_reconciliation_is_idempotent_after_ack_failure(tmp_path: Path) -> None:
    _, profile, logs, history, _, submissions = make_services(tmp_path)
    history.record_execution(
        profile.profile_id,
        "l0_two_values",
        CORRECT_SOURCE,
        stored_result(SubmissionMode.FULL, JudgeStatus.AC),
    )

    submissions.reconcile(profile.profile_id)
    first = logs.load_log(profile.profile_id)
    submissions.reconcile(profile.profile_id)
    second = logs.load_log(profile.profile_id)

    assert first == second
    assert second.progress["l0_two_values"].attempt_count == 1
    assert second.progress["l0_two_values"].solved


def test_delete_removes_source_and_results_but_not_progress(tmp_path: Path) -> None:
    paths, profile, logs, history, _, submissions = make_services(tmp_path)
    submissions.submit(profile.profile_id, "l0_two_values", CORRECT_SOURCE)
    snapshot = history.list_snapshots(
        profile.profile_id,
        "l0_two_values",
        limit=20,
        offset=0,
    )[0]

    assert history.delete_snapshot(
        profile.profile_id,
        "l0_two_values",
        snapshot.snapshot_id,
    )
    database_path = paths.code_history_dir / f"{profile.profile_id}.sqlite3"

    assert history.count_snapshots(profile.profile_id, "l0_two_values") == 0
    assert CORRECT_SOURCE.encode() not in database_path.read_bytes()
    assert logs.load_log(profile.profile_id).progress["l0_two_values"].solved
