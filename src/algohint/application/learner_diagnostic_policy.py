"""Build learner-safe diagnostics from private LocalJudge results."""

import re
from uuid import uuid4

from algohint.application.dto import LearnerDiagnostic
from algohint.domain.enums import JudgeStatus, TestVisibility
from algohint.domain.models import JudgePolicy, JudgeResult


class LearnerDiagnosticPolicy:
    """Expose useful source locations while withholding hidden-case values.

    Exception messages can include values derived from stdin. Hidden-case failures
    therefore expose only the exception type and learner source line, whereas
    compile failures and public-sample failures may include a bounded excerpt.
    """

    _detail_limit = 4_096
    _source_location = re.compile(r'File "(?P<path>[^"]*submission\.py)", line (?P<line>[0-9]+)')
    _exception_line = re.compile(
        r"^(?P<name>[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Interrupt|Exit)?)(?::|$)"
    )

    @classmethod
    def _source_line(cls, stderr: str) -> int | None:
        matches = list(cls._source_location.finditer(stderr))
        return int(matches[-1].group("line")) if matches else None

    @classmethod
    def _exception_summary(cls, stderr: str, fallback: str) -> str:
        for line in reversed(stderr.splitlines()):
            stripped = line.strip()
            match = cls._exception_line.match(stripped)
            if match:
                return match.group("name")
        return fallback

    @classmethod
    def _safe_excerpt(cls, stderr: str) -> str | None:
        """Keep only the learner frame and final exception, never internal paths."""

        lines = stderr.splitlines()
        selected: list[str] = []
        for index, line in enumerate(lines):
            if cls._source_location.search(line):
                selected.append(
                    cls._source_location.sub('File "submission.py", line \\g<line>', line)
                )
                for following in lines[index + 1 : index + 3]:
                    if following.strip() and not following.lstrip().startswith('File "'):
                        selected.append(following)
        for line in reversed(lines):
            if cls._exception_line.match(line.strip()):
                selected.append(line)
                break
        excerpt = "\n".join(dict.fromkeys(selected)).strip()
        if not excerpt:
            return None
        encoded = excerpt.encode("utf-8", errors="replace")[: cls._detail_limit]
        return encoded.decode("utf-8", errors="replace")

    def create(self, result: JudgeResult, policy: JudgePolicy) -> LearnerDiagnostic | None:
        """Return a diagnostic whose detail is safe for the failed-case visibility."""

        if result.status in {JudgeStatus.AC, JudgeStatus.WA}:
            return None
        if result.status is JudgeStatus.TLE:
            elapsed = result.elapsed_ms if result.elapsed_ms is not None else 0
            return LearnerDiagnostic(
                status=result.status,
                summary=f"実行時間が制限の{policy.timeout_seconds:.1f}秒を超えました。",
                details=f"計測時間: {elapsed} ms",
                redacted=result.failed_case is not None
                and result.failed_case.visibility is TestVisibility.HIDDEN,
            )
        if result.status is JudgeStatus.IE:
            return LearnerDiagnostic(
                status=result.status,
                summary="判定処理で内部エラーが発生しました。",
                redacted=True,
                diagnostic_id=uuid4().hex[:12],
            )

        stderr = result.stderr or ""
        source_line = self._source_line(stderr)
        summary = self._exception_summary(
            stderr, "コンパイルエラー" if result.status is JudgeStatus.CE else "実行時エラー"
        )
        hidden_failure = (
            result.failed_case is not None
            and result.failed_case.visibility is TestVisibility.HIDDEN
        )
        # Hidden-case exception messages may echo secret input, so only CE and
        # public-sample failures receive an excerpt.
        details = (
            None
            if hidden_failure and result.status is JudgeStatus.RE
            else self._safe_excerpt(stderr)
        )
        return LearnerDiagnostic(
            status=result.status,
            summary=summary,
            source_line=source_line,
            details=details,
            redacted=hidden_failure,
        )
