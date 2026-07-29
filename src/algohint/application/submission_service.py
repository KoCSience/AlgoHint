"""Code submission use case and learner-safe result filtering."""

from datetime import UTC, datetime

from algohint.application.dto import SubmissionView
from algohint.application.learner_diagnostic_policy import LearnerDiagnosticPolicy
from algohint.domain.enums import JudgeStatus, SubmissionMode, TestVisibility
from algohint.domain.models import JudgePolicy, LearningLog, ProblemProgress
from algohint.domain.ports import JudgeRunner, LearningLogRepository, ProblemRepository


class SubmissionService:
    """Judge source then retain only aggregate progress, never the source itself."""

    def __init__(
        self,
        problems: ProblemRepository,
        logs: LearningLogRepository,
        judge: JudgeRunner,
        policy: JudgePolicy | None = None,
        diagnostic_policy: LearnerDiagnosticPolicy | None = None,
    ) -> None:
        self._problems = problems
        self._logs = logs
        self._judge = judge
        self._policy = policy or JudgePolicy()
        self._diagnostic_policy = diagnostic_policy or LearnerDiagnosticPolicy()

    @staticmethod
    def _updated_log(log: LearningLog, problem_id: str, status: JudgeStatus) -> LearningLog:
        current = log.progress.get(problem_id, ProblemProgress())
        solved = current.solved or status is JudgeStatus.AC
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
        cases = self._problems.get_tests(problem_id, include_hidden=mode is SubmissionMode.FULL)
        result = self._judge.judge(source, cases, self._policy)
        log = self._logs.load_log(profile_id)
        self._logs.save_log(self._updated_log(log, problem_id, result.status))
        message = {
            JudgeStatus.AC: "ACです。解説を開けます。",
            JudgeStatus.WA: "WAです。出力と境界条件を見直してみましょう。",
            JudgeStatus.RE: "REです。入力処理や例外になり得る箇所を確認してみましょう。",
            JudgeStatus.TLE: "TLEです。制約に対する繰り返し回数を確認してみましょう。",
            JudgeStatus.CE: "CEです。構文やインデントを確認してみましょう。",
            JudgeStatus.IE: "判定側で問題が起きました。時間を置いて再実行してください。",
        }[result.status]
        failed = result.failed_case
        reveal_sample = failed is not None and failed.visibility is TestVisibility.SAMPLE
        return SubmissionView(
            status=result.status,
            passed_count=result.passed_count,
            total_count=result.total_count,
            elapsed_ms=result.elapsed_ms,
            message=message,
            diagnostic=self._diagnostic_policy.create(result, self._policy),
            sample_input=failed.input_text if reveal_sample and failed is not None else None,
            actual_output=result.stdout
            if reveal_sample and failed is not None and result.status is JudgeStatus.WA
            else None,
            expected_output=failed.expected_output
            if reveal_sample and failed is not None and result.status is JudgeStatus.WA
            else None,
        )
