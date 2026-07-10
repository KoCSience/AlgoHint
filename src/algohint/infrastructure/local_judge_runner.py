"""Deterministic LocalJudge implementation."""

from algohint.domain.enums import JudgeStatus
from algohint.domain.models import JudgePolicy, JudgeResult, TestCase
from algohint.domain.policies import outputs_match
from algohint.infrastructure.subprocess_executor import SubprocessExecutor


class LocalJudgeRunner:
    """Judge each testcase in order and stop at the first non-passing result."""

    def __init__(self, executor: SubprocessExecutor | None = None) -> None:
        self._executor = executor or SubprocessExecutor()

    def judge(self, source: str, cases: list[TestCase], policy: JudgePolicy) -> JudgeResult:
        """Return a rich internal result without deciding what the learner may see."""

        if not cases:
            return JudgeResult(
                status=JudgeStatus.IE,
                passed_count=0,
                total_count=0,
                debug_message="No testcase was supplied.",
            )
        passed = 0
        elapsed_ms = 0
        for case in cases:
            outcome = self._executor.run(source, case.input_text, policy)
            elapsed_ms += outcome.elapsed_ms
            if outcome.status is not JudgeStatus.AC:
                return JudgeResult(
                    status=outcome.status,
                    passed_count=passed,
                    total_count=len(cases),
                    elapsed_ms=elapsed_ms,
                    stdout=outcome.stdout,
                    stderr=outcome.stderr,
                    failed_case=case,
                    debug_message=outcome.stderr or None,
                )
            if not outputs_match(outcome.stdout, case.expected_output):
                return JudgeResult(
                    status=JudgeStatus.WA,
                    passed_count=passed,
                    total_count=len(cases),
                    elapsed_ms=elapsed_ms,
                    stdout=outcome.stdout,
                    failed_case=case,
                )
            passed += 1
        return JudgeResult(
            status=JudgeStatus.AC,
            passed_count=passed,
            total_count=len(cases),
            elapsed_ms=elapsed_ms,
        )
