"""Code submission use case and learner-safe result filtering."""

from datetime import UTC, datetime

from algohint.application.dto import SubmissionView
from algohint.application.code_workspace_service import CodeWorkspaceService
from algohint.application.learner_diagnostic_policy import LearnerDiagnosticPolicy
from algohint.domain.enums import JudgeStatus, SubmissionMode, TestVisibility
from algohint.domain.models import (
    JudgePolicy,
    LearningLog,
    ProblemProgress,
    StoredExecutionResult,
    StoredLearnerDiagnostic,
)
from algohint.domain.ports import (
    CodeHistoryRepository,
    JudgeRunner,
    LearningLogRepository,
    ProblemRepository,
)


class SubmissionService:
    """Judge source, retain a safe result snapshot, then reconcile aggregates."""

    def __init__(
        self,
        problems: ProblemRepository,
        logs: LearningLogRepository,
        judge: JudgeRunner,
        history: CodeHistoryRepository | None = None,
        policy: JudgePolicy | None = None,
        diagnostic_policy: LearnerDiagnosticPolicy | None = None,
    ) -> None:
        self._problems = problems
        self._logs = logs
        self._judge = judge
        self._history = history
        self._policy = policy or JudgePolicy()
        self._diagnostic_policy = diagnostic_policy or LearnerDiagnosticPolicy()

    @staticmethod
    def _updated_log(
        log: LearningLog,
        problem_id: str,
        status: JudgeStatus,
        mode: SubmissionMode,
    ) -> LearningLog:
        current = log.progress.get(problem_id, ProblemProgress())
        solved = current.solved or (
            mode is SubmissionMode.FULL and status is JudgeStatus.AC
        )
        progress = current.model_copy(
            update={
                "attempt_count": current.attempt_count + 1,
                "failed_attempt_count": current.failed_attempt_count
                + (0 if status is JudgeStatus.AC else 1),
                "solved": solved,
                "last_status": status,
                "completed_at": datetime.now(UTC)
                if solved and not current.solved
                else current.completed_at,
            }
        )
        return log.model_copy(update={"progress": {**log.progress, problem_id: progress}})

    def submit(
        self,
        profile_id: str,
        problem_id: str,
        source: str,
        mode: SubmissionMode = SubmissionMode.FULL,
    ) -> SubmissionView:
        CodeWorkspaceService.validate_source(source)
        if self._history is not None:
            self.reconcile(profile_id)
        cases = self._problems.get_tests(problem_id, include_hidden=mode is SubmissionMode.FULL)
        result = self._judge.judge(source, cases, self._policy)
        log = self._logs.load_log(profile_id)
        current = log.progress.get(problem_id, ProblemProgress())
        newly_completed = (
            mode is SubmissionMode.FULL
            and result.status is JudgeStatus.AC
            and not current.solved
        )
        message = {
            JudgeStatus.AC: (
                "AC、おめでとうございます！固定小テストに進みましょう。"
                if mode is SubmissionMode.FULL
                else "公開サンプルはACです。全テストで提出して完了を確認しましょう。"
            ),
            JudgeStatus.WA: "WAです。出力と境界条件を見直してみましょう。",
            JudgeStatus.RE: "REです。入力処理や例外になり得る箇所を確認してみましょう。",
            JudgeStatus.TLE: "TLEです。制約に対する繰り返し回数を確認してみましょう。",
            JudgeStatus.CE: "CEです。構文やインデントを確認してみましょう。",
            JudgeStatus.IE: "判定側で問題が起きました。時間を置いて再実行してください。",
        }[result.status]
        failed = result.failed_case
        reveal_sample = failed is not None and failed.visibility is TestVisibility.SAMPLE
        view = SubmissionView(
            status=result.status,
            passed_count=result.passed_count,
            total_count=result.total_count,
            elapsed_ms=result.elapsed_ms,
            message=message,
            newly_completed=newly_completed,
            diagnostic=self._diagnostic_policy.create(result, self._policy),
            sample_input=failed.input_text if reveal_sample and failed is not None else None,
            actual_output=result.stdout
            if reveal_sample and failed is not None and result.status is JudgeStatus.WA
            else None,
            expected_output=failed.expected_output
            if reveal_sample and failed is not None and result.status is JudgeStatus.WA
            else None,
        )
        if self._history is None:
            self._logs.save_log(self._updated_log(log, problem_id, result.status, mode))
            return view
        self._history.record_execution(
            profile_id,
            problem_id,
            source,
            self._stored_result(view, mode),
        )
        self.reconcile(profile_id)
        return view

    def reconcile(self, profile_id: str) -> None:
        """Apply crash-safe SQLite progress events to the aggregate JSON log."""

        if self._history is None:
            return
        log = self._logs.load_log(profile_id)
        # A crash after JSON replacement but before SQLite cleanup is harmless:
        # the persisted sequence prevents the same event from being counted twice.
        self._history.acknowledge_progress(
            profile_id,
            through_sequence=log.last_applied_submission_sequence,
        )
        pending = self._history.pending_progress(
            profile_id,
            after_sequence=log.last_applied_submission_sequence,
        )
        if not pending:
            return
        updated = log
        for event in pending:
            updated = self._updated_log(
                updated,
                event.problem_id,
                event.status,
                event.mode,
            )
        last_sequence = pending[-1].sequence
        updated = updated.model_copy(
            update={"last_applied_submission_sequence": last_sequence}
        )
        self._logs.save_log(updated)
        self._history.acknowledge_progress(
            profile_id,
            through_sequence=last_sequence,
        )

    @staticmethod
    def _stored_result(
        view: SubmissionView,
        mode: SubmissionMode,
    ) -> StoredExecutionResult:
        diagnostic = (
            StoredLearnerDiagnostic(
                status=view.diagnostic.status,
                summary=view.diagnostic.summary,
                source_line=view.diagnostic.source_line,
                source_column=view.diagnostic.source_column,
                details=view.diagnostic.details,
                redacted=view.diagnostic.redacted,
                diagnostic_id=view.diagnostic.diagnostic_id,
            )
            if view.diagnostic is not None
            else None
        )
        return StoredExecutionResult(
            mode=mode,
            executed_at=datetime.now(UTC),
            status=view.status,
            passed_count=view.passed_count,
            total_count=view.total_count,
            elapsed_ms=view.elapsed_ms,
            message=view.message,
            diagnostic=diagnostic,
            sample_input=view.sample_input,
            actual_output=view.actual_output,
            expected_output=view.expected_output,
        )
