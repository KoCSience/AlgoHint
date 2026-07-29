"""Completion-gated authored review and deterministic quiz grading."""

from datetime import UTC, datetime

from algohint.application.dto import (
    CompletionReviewView,
    PublicQuizOption,
    PublicQuizQuestion,
    QuizQuestionFeedback,
    QuizHistoryPage,
    QuizResult,
)
from algohint.domain.enums import ReviewHistoryKind
from algohint.domain.models import (
    ProblemProgress,
    QuizAttempt,
    StoredQuizFeedback,
)
from algohint.domain.ports import (
    LearningLogRepository,
    ProblemRepository,
    ReviewHistoryRepository,
)

QUIZ_HISTORY_PAGE_SIZE = 20


class CompletionRequiredError(PermissionError):
    """Raised when review content is requested before AC or give-up."""


class CompletionReviewService:
    """Release reviewed material without exposing answer keys before grading."""

    def __init__(
        self,
        problems: ProblemRepository,
        logs: LearningLogRepository,
        history: ReviewHistoryRepository,
    ) -> None:
        self._problems = problems
        self._logs = logs
        self._history = history

    def view(self, profile_id: str, problem_id: str) -> CompletionReviewView | None:
        """Return public material only after the authoritative progress gate."""

        progress = self._progress(profile_id, problem_id)
        if not (progress.solved or progress.gave_up):
            return None
        problem = self._problems.get_problem(problem_id)
        material = self._problems.get_review_material(problem_id)
        questions = tuple(
            PublicQuizQuestion(
                question_id=question.question_id,
                topic=question.topic.value,
                prompt=question.prompt,
                options=tuple(
                    PublicQuizOption(option_id=option.option_id, text=option.text)
                    for option in question.options
                ),
            )
            for question in material.questions
        )
        return CompletionReviewView(
            explanation=problem.explanation,
            material_version=material.version,
            questions=questions,
        )

    def grade(
        self,
        profile_id: str,
        problem_id: str,
        answers: tuple[str | None, ...],
    ) -> QuizResult:
        """Grade exactly five selected option IDs after rechecking completion."""

        if self.view(profile_id, problem_id) is None:
            raise CompletionRequiredError("ACまたはギブアップ後に小テストへ回答できます。")
        material = self._problems.get_review_material(problem_id)
        if len(answers) != len(material.questions) or any(answer is None for answer in answers):
            raise ValueError("5問すべてに回答してください。")

        feedback: list[QuizQuestionFeedback] = []
        for question, selected_id in zip(material.questions, answers, strict=True):
            assert selected_id is not None
            options = {option.option_id: option for option in question.options}
            selected = options.get(selected_id)
            if selected is None:
                raise ValueError("選択肢を確認して、もう一度回答してください。")
            correct = options[question.correct_option_id]
            feedback.append(
                QuizQuestionFeedback(
                    question_id=question.question_id,
                    prompt=question.prompt,
                    selected_option_id=selected.option_id,
                    selected_text=selected.text,
                    correct_option_id=correct.option_id,
                    correct_text=correct.text,
                    correct=selected.option_id == correct.option_id,
                    explanation=question.explanation,
                )
            )
        score = sum(item.correct for item in feedback)
        attempted_at = datetime.now(UTC)
        attempt = QuizAttempt(
            attempted_at=attempted_at,
            material_version=material.version,
            score=score,
            total=len(feedback),
            feedback=tuple(
                StoredQuizFeedback(
                    question_id=item.question_id,
                    prompt=item.prompt,
                    selected_option_id=item.selected_option_id,
                    selected_text=item.selected_text,
                    correct_option_id=item.correct_option_id,
                    correct_text=item.correct_text,
                    correct=item.correct,
                    explanation=item.explanation,
                )
                for item in feedback
            ),
        )
        quota = self._history.save_quiz_attempt(profile_id, problem_id, attempt)
        return QuizResult(
            material_version=material.version,
            score=score,
            total=len(feedback),
            feedback=tuple(feedback),
            attempted_at=attempted_at,
            quota=quota,
        )

    def quiz_history(
        self,
        profile_id: str,
        problem_id: str,
        *,
        page: int = 0,
    ) -> QuizHistoryPage:
        """Load one bounded page after rechecking the completion gate."""

        if page < 0:
            raise ValueError("page must not be negative")
        if self.view(profile_id, problem_id) is None:
            raise CompletionRequiredError("ACまたはギブアップ後に履歴を表示できます。")
        offset = page * QUIZ_HISTORY_PAGE_SIZE
        records = self._history.list_records(
            profile_id,
            problem_id,
            kind=ReviewHistoryKind.QUIZ_ATTEMPT.value,
            limit=QUIZ_HISTORY_PAGE_SIZE,
            offset=offset,
        )
        attempts = tuple(
            QuizAttempt.model_validate_json(record.payload_json) for record in records
        )
        return QuizHistoryPage(
            attempts=attempts,
            page=page,
            page_size=QUIZ_HISTORY_PAGE_SIZE,
            total_count=self._history.count_records(
                profile_id,
                problem_id,
                kind=ReviewHistoryKind.QUIZ_ATTEMPT.value,
            ),
            quota=self._history.quota_status(profile_id),
        )

    def _progress(self, profile_id: str, problem_id: str) -> ProblemProgress:
        return self._logs.load_log(profile_id).progress.get(
            problem_id,
            ProblemProgress(),
        )
