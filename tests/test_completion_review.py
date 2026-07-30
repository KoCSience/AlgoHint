from pathlib import Path

import pytest

from algohint.application.completion_review_service import (
    CompletionRequiredError,
    CompletionReviewService,
    QuizRequiredError,
)
from algohint.application.profile_service import ProfileService
from algohint.application.submission_service import SubmissionService
from algohint.domain.enums import SubmissionMode
from algohint.domain.enums import (
    CodeReviewCategory,
    HintProviderId,
)
from algohint.domain.models import (
    CodeReviewPoint,
    CodeReviewRequest,
    GeneratedCodeReview,
    GeneratedPersonalizedQuiz,
    GeneratedPersonalizedQuizQuestion,
    PersonalizedQuizRequest,
    ProviderAvailability,
)
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.local_judge_runner import LocalJudgeRunner
from algohint.infrastructure.sqlite_review_history_repository import (
    SqliteReviewHistoryRepository,
)

DATA_DIR = Path(__file__).parents[1] / "data"
CORRECT_SOURCE = "a, b = map(int, input().split())\nprint(a + b)"


class FakeReviewProvider:
    def __init__(self, *, sends_data_off_device: bool = False) -> None:
        self.requests: list[CodeReviewRequest] = []
        self.quiz_requests: list[PersonalizedQuizRequest] = []
        self._availability = ProviderAvailability(
            available=True,
            sends_data_off_device=sends_data_off_device,
        )

    def availability(self) -> ProviderAvailability:
        return self._availability

    def generate_review(self, request: CodeReviewRequest) -> GeneratedCodeReview:
        self.requests.append(request)
        return GeneratedCodeReview(
            algorithm_recap="二つの整数を読み取り、和を出力する処理です。",
            strengths=("処理が簡潔です。",),
            improvements=(
                CodeReviewPoint(
                    category=CodeReviewCategory.READABILITY,
                    title="名前の意図",
                    feedback="入力値との対応が伝わる命名を維持しましょう。",
                ),
            ),
            provider="fake",
            model_name="fake-review",
        )

    def generate_quiz(
        self,
        request: PersonalizedQuizRequest,
    ) -> GeneratedPersonalizedQuiz:
        self.quiz_requests.append(request)
        count = 3 if request.mode.value == "fixed_3" else 2
        return GeneratedPersonalizedQuiz(
            questions=tuple(
                GeneratedPersonalizedQuizQuestion(
                    focus=CodeReviewCategory.EDGE_CASES,
                    prompt=f"コード固有の境界条件 {index}",
                    options=("確認する", "確認しない", "無関係"),
                    correct_option_index=0,
                    explanation="境界条件の確認が必要だからです。",
                )
                for index in range(count)
            ),
            provider="fake",
            model_name="fake-quiz",
        )


def make_review_services(
    tmp_path: Path,
    provider: FakeReviewProvider | None = None,
):
    problems = JsonProblemRepository(DataPaths(DATA_DIR))
    runtime_paths = DataPaths(tmp_path / "runtime-data")
    profiles = JsonProfileRepository(runtime_paths)
    logs = JsonLearningLogRepository(runtime_paths, profiles)
    profile = ProfileService(profiles, logs).create_profile("学習者")
    return (
        CompletionReviewService(
            problems,
            profiles,
            logs,
            SqliteReviewHistoryRepository(runtime_paths, profiles),
            {HintProviderId.OPENAI: provider} if provider is not None else {},
        ),
        SubmissionService(problems, logs, LocalJudgeRunner()),
        problems,
        profile.profile_id,
    )


def complete_authored_quiz(
    reviews: CompletionReviewService,
    problems: JsonProblemRepository,
    profile_id: str,
) -> None:
    """Unlock post-quiz material through the same deterministic grading path."""

    material = problems.get_review_material("l0_two_values")
    reviews.grade(
        profile_id,
        "l0_two_values",
        tuple(question.correct_option_id for question in material.questions),
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
    with pytest.raises(QuizRequiredError):
        reviews.get_explanation(profile_id, "l0_two_values")
    with pytest.raises(ValueError, match="5問すべて"):
        reviews.grade(profile_id, "l0_two_values", (*correct_answers[:-1], None))

    result = reviews.grade(profile_id, "l0_two_values", correct_answers)
    history = reviews.quiz_history(profile_id, "l0_two_values")

    assert result.score == result.total == 5
    assert all(item.correct for item in result.feedback)
    assert history.total_count == 1
    assert history.attempts[0].score == 5
    assert reviews.view(profile_id, "l0_two_values").authored_quiz_completed
    assert "二つの値" in reviews.get_explanation(profile_id, "l0_two_values")


def test_code_review_requires_consent_and_persists_only_generated_feedback(
    tmp_path: Path,
) -> None:
    provider = FakeReviewProvider(sends_data_off_device=True)
    reviews, submissions, problems, profile_id = make_review_services(tmp_path, provider)
    submissions.submit(profile_id, "l0_two_values", CORRECT_SOURCE, SubmissionMode.FULL)
    complete_authored_quiz(reviews, problems, profile_id)

    with pytest.raises(PermissionError, match="同意"):
        reviews.generate_code_review(
            profile_id,
            "l0_two_values",
            CORRECT_SOURCE,
            cloud_consent=False,
        )

    receipt = reviews.generate_code_review(
        profile_id,
        "l0_two_values",
        CORRECT_SOURCE,
        cloud_consent=True,
    )
    history = reviews.code_review_history(profile_id, "l0_two_values")

    assert receipt.entry.review.provider == "fake"
    assert history.total_count == 1
    assert history.entries[0] == receipt.entry
    assert provider.requests[0].source_code == CORRECT_SOURCE
    assert CORRECT_SOURCE not in history.entries[0].model_dump_json()


def test_code_review_rejects_provider_output_that_repeats_source(
    tmp_path: Path,
) -> None:
    class QuotingProvider(FakeReviewProvider):
        def generate_review(self, request: CodeReviewRequest) -> GeneratedCodeReview:
            generated = super().generate_review(request)
            return generated.model_copy(update={"algorithm_recap": request.source_code})

    provider = QuotingProvider()
    reviews, submissions, problems, profile_id = make_review_services(tmp_path, provider)
    submissions.submit(profile_id, "l0_two_values", CORRECT_SOURCE, SubmissionMode.FULL)
    complete_authored_quiz(reviews, problems, profile_id)

    with pytest.raises(RuntimeError, match="再掲"):
        reviews.generate_code_review(
            profile_id,
            "l0_two_values",
            CORRECT_SOURCE,
            cloud_consent=False,
        )

    assert reviews.code_review_history(profile_id, "l0_two_values").total_count == 0


def test_code_review_history_is_paginated_newest_first(tmp_path: Path) -> None:
    provider = FakeReviewProvider()
    reviews, submissions, problems, profile_id = make_review_services(tmp_path, provider)
    submissions.submit(profile_id, "l0_two_values", CORRECT_SOURCE, SubmissionMode.FULL)
    complete_authored_quiz(reviews, problems, profile_id)

    for _ in range(21):
        reviews.generate_code_review(
            profile_id,
            "l0_two_values",
            CORRECT_SOURCE,
            cloud_consent=False,
        )

    newest_page = reviews.code_review_history(profile_id, "l0_two_values")
    oldest_page = reviews.code_review_history(profile_id, "l0_two_values", page=1)

    assert newest_page.total_count == 21
    assert len(newest_page.entries) == newest_page.page_size == 20
    assert len(oldest_page.entries) == 1
    assert newest_page.entries[0].reviewed_at >= oldest_page.entries[0].reviewed_at


def test_personalized_quiz_is_generated_after_ac_but_released_after_fixed_quiz(
    tmp_path: Path,
) -> None:
    provider = FakeReviewProvider()
    reviews, submissions, problems, profile_id = make_review_services(tmp_path, provider)
    submissions.submit(profile_id, "l0_two_values", CORRECT_SOURCE, SubmissionMode.FULL)

    receipt = reviews.generate_personalized_quiz(
        profile_id,
        "l0_two_values",
        CORRECT_SOURCE,
        cloud_consent=False,
    )
    with pytest.raises(QuizRequiredError):
        reviews.view_personalized_quiz(profile_id, "l0_two_values")

    complete_authored_quiz(reviews, problems, profile_id)
    public_quiz = reviews.view_personalized_quiz(profile_id, "l0_two_values")

    assert public_quiz is not None
    assert public_quiz.quiz_set_id == receipt.quiz_set_id
    assert len(public_quiz.questions) == 2
    assert all(
        not hasattr(question, "correct_option_id")
        for question in public_quiz.questions
    )
    result = reviews.grade_personalized_quiz(
        profile_id,
        "l0_two_values",
        public_quiz.quiz_set_id,
        tuple(question.options[0].option_id for question in public_quiz.questions),
    )
    assert result.score == result.total == 2
    assert provider.quiz_requests[0].source_code == CORRECT_SOURCE
