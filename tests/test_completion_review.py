from pathlib import Path

import pytest

from algohint.application.completion_review_service import (
    CompletionRequiredError,
    CompletionReviewService,
)
from algohint.application.profile_service import ProfileService
from algohint.application.submission_service import SubmissionService
from algohint.domain.enums import SubmissionMode
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.local_judge_runner import LocalJudgeRunner

DATA_DIR = Path(__file__).parents[1] / "data"
CORRECT_SOURCE = "a, b = map(int, input().split())\nprint(a + b)"


def make_review_services(tmp_path: Path):
    problems = JsonProblemRepository(DataPaths(DATA_DIR))
    runtime_paths = DataPaths(tmp_path / "runtime-data")
    profiles = JsonProfileRepository(runtime_paths)
    logs = JsonLearningLogRepository(runtime_paths, profiles)
    profile = ProfileService(profiles, logs).create_profile("学習者")
    return (
        CompletionReviewService(problems, logs),
        SubmissionService(problems, logs, LocalJudgeRunner()),
        problems,
        profile.profile_id,
    )


def test_sample_ac_does_not_unlock_completion_review(tmp_path: Path) -> None:
    reviews, submissions, _, profile_id = make_review_services(tmp_path)

    submissions.submit(
        profile_id,
        "l0_two_values",
        CORRECT_SOURCE,
        SubmissionMode.SAMPLE,
    )

    assert reviews.view(profile_id, "l0_two_values") is None


def test_full_ac_releases_five_answer_free_questions(tmp_path: Path) -> None:
    reviews, submissions, _, profile_id = make_review_services(tmp_path)
    submissions.submit(profile_id, "l0_two_values", CORRECT_SOURCE, SubmissionMode.FULL)

    view = reviews.view(profile_id, "l0_two_values")

    assert view is not None
    assert len(view.questions) == 5
    assert all(not hasattr(question, "correct_option_id") for question in view.questions)


def test_quiz_requires_completion_and_all_valid_answers(tmp_path: Path) -> None:
    reviews, submissions, problems, profile_id = make_review_services(tmp_path)
    material = problems.get_review_material("l0_two_values")
    correct_answers = tuple(question.correct_option_id for question in material.questions)

    with pytest.raises(CompletionRequiredError):
        reviews.grade(profile_id, "l0_two_values", correct_answers)

    submissions.submit(profile_id, "l0_two_values", CORRECT_SOURCE, SubmissionMode.FULL)
    with pytest.raises(ValueError, match="5問すべて"):
        reviews.grade(profile_id, "l0_two_values", (*correct_answers[:-1], None))

    result = reviews.grade(profile_id, "l0_two_values", correct_answers)

    assert result.score == result.total == 5
    assert all(item.correct for item in result.feedback)
