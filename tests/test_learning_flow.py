from pathlib import Path

from algohint.application.explanation_service import ExplanationService
from algohint.application.hint_service import HintService
from algohint.application.learning_report_service import LearningReportService
from algohint.application.profile_service import ProfileService
from algohint.application.submission_service import SubmissionService
from algohint.domain.enums import JudgeStatus, SubmissionMode
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.local_judge_runner import LocalJudgeRunner


DATA_DIR = Path(__file__).parents[1] / "data"


def make_services(tmp_path: Path):
    problems = JsonProblemRepository(DataPaths(DATA_DIR))
    paths = DataPaths(tmp_path / "runtime-data")
    profile_repository = JsonProfileRepository(paths)
    logs = JsonLearningLogRepository(paths, profile_repository)
    profile = ProfileService(profile_repository, logs).create_profile("学習者")
    return problems, logs, profile


def test_hidden_failure_is_not_revealed_to_learner(tmp_path: Path) -> None:
    problems, logs, profile = make_services(tmp_path)
    source = "a, b = map(int, input().split())\nprint(1 if a == 0 else a + b)"

    result = SubmissionService(problems, logs, LocalJudgeRunner()).submit(
        profile.profile_id, "l0_two_values", source
    )

    assert result.status is JudgeStatus.WA
    assert result.sample_input is None
    assert result.expected_output is None


def test_hint_explanation_and_report_flow(tmp_path: Path) -> None:
    problems, logs, profile = make_services(tmp_path)
    hints = HintService(problems, logs)
    explanations = ExplanationService(problems, logs)
    submissions = SubmissionService(problems, logs, LocalJudgeRunner())

    hint = hints.request(profile.profile_id, "l0_two_values")
    assert hint.leak_checked
    assert explanations.get_explanation(profile.profile_id, "l0_two_values") is None

    result = submissions.submit(
        profile.profile_id, "l0_two_values", "a, b = map(int, input().split())\nprint(a + b)"
    )
    assert result.status is JudgeStatus.AC
    assert explanations.get_explanation(profile.profile_id, "l0_two_values") is not None

    report = LearningReportService(problems, logs).report(profile.profile_id)
    assert report.solved_count == 1
    assert report.average_hint_count == 1.0


def test_profiles_have_separate_logs(tmp_path: Path) -> None:
    problems = JsonProblemRepository(DataPaths(DATA_DIR))
    paths = DataPaths(tmp_path / "runtime-data")
    profile_repository = JsonProfileRepository(paths)
    logs = JsonLearningLogRepository(paths, profile_repository)
    profiles = ProfileService(profile_repository, logs)
    first = profiles.create_profile("一人目")
    second = profiles.create_profile("二人目")

    SubmissionService(problems, logs, LocalJudgeRunner()).submit(
        first.profile_id, "l0_two_values", "print(0)"
    )

    assert logs.load_log(first.profile_id).progress
    assert not logs.load_log(second.profile_id).progress


def test_public_runtime_error_shows_sanitized_source_detail(tmp_path: Path) -> None:
    problems, logs, profile = make_services(tmp_path)

    result = SubmissionService(problems, logs, LocalJudgeRunner()).submit(
        profile.profile_id,
        "l0_two_values",
        "raise RuntimeError('public detail')",
        SubmissionMode.SAMPLE,
    )

    assert result.status is JudgeStatus.RE
    assert result.diagnostic is not None
    assert result.diagnostic.summary == "RuntimeError"
    assert result.diagnostic.source_line == 1
    assert result.diagnostic.details is not None
    assert "public detail" in result.diagnostic.details
    assert "/tmp/" not in result.diagnostic.details


def test_hidden_runtime_error_redacts_exception_message(tmp_path: Path) -> None:
    problems, logs, profile = make_services(tmp_path)
    source = (
        "a, b = map(int, input().split())\n"
        "if a == 0:\n"
        "    raise RuntimeError(f'hidden values: {a} {b}')\n"
        "print(a + b)\n"
    )

    result = SubmissionService(problems, logs, LocalJudgeRunner()).submit(
        profile.profile_id, "l0_two_values", source
    )

    assert result.status is JudgeStatus.RE
    assert result.diagnostic is not None
    assert result.diagnostic.summary == "RuntimeError"
    assert result.diagnostic.source_line == 3
    assert result.diagnostic.redacted
    assert result.diagnostic.details is None
