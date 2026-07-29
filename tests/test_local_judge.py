import pytest

from algohint.domain.enums import JudgeStatus, TestVisibility as Visibility
from algohint.domain.models import JudgePolicy, TestCase as JudgeTestCase
from algohint.infrastructure.local_judge_runner import LocalJudgeRunner


CASES = [
    JudgeTestCase(
        case_id="sample",
        input_text="2 3\n",
        expected_output="5\n",
        visibility=Visibility.SAMPLE,
    ),
    JudgeTestCase(
        case_id="hidden",
        input_text="0 0\n",
        expected_output="0\n",
        visibility=Visibility.HIDDEN,
    ),
]


def test_judge_accepts_correct_code_and_trimmed_output() -> None:
    result = LocalJudgeRunner().judge(
        "a, b = map(int, input().split())\nprint(a + b, '  ')", CASES, JudgePolicy()
    )

    assert result.status is JudgeStatus.AC
    assert result.passed_count == 2


def test_judge_reports_wa_with_failed_case() -> None:
    result = LocalJudgeRunner().judge("print(0)", CASES, JudgePolicy())

    assert result.status is JudgeStatus.WA
    assert result.failed_case is not None
    assert result.failed_case.case_id == "sample"


def test_judge_reports_runtime_and_compile_errors() -> None:
    judge = LocalJudgeRunner()

    assert judge.judge("raise RuntimeError('x')", CASES, JudgePolicy()).status is JudgeStatus.RE
    assert judge.judge("if True print('x')", CASES, JudgePolicy()).status is JudgeStatus.CE


def test_judge_reports_timeout() -> None:
    result = LocalJudgeRunner().judge(
        "while True:\n    pass", CASES, JudgePolicy(timeout_seconds=0.2)
    )

    assert result.status is JudgeStatus.TLE


def test_judge_does_not_inherit_llm_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Learner code receives a minimal environment, not the web app's keys."""

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-submission")
    result = LocalJudgeRunner().judge(
        "import os\nprint(os.environ.get('OPENAI_API_KEY', 'not-set'))",
        [
            JudgeTestCase(
                case_id="environment",
                input_text="",
                expected_output="not-set\n",
                visibility=Visibility.SAMPLE,
            )
        ],
        JudgePolicy(),
    )

    assert result.status is JudgeStatus.AC
