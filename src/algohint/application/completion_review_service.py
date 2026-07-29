"""Completion-gated authored review and deterministic quiz grading."""

import hashlib
from datetime import UTC, datetime
from typing import Mapping

from algohint.application.dto import (
    CodeReviewHistoryPage,
    CodeReviewReceipt,
    CompletionReviewView,
    PublicQuizOption,
    PublicQuizQuestion,
    QuizQuestionFeedback,
    QuizHistoryPage,
    QuizResult,
)
from algohint.application.hint_safety_policy import HintSafetyPolicy
from algohint.domain.enums import (
    CompletionReason,
    HintProviderId,
    ProviderFailureReason,
    ReviewHistoryKind,
)
from algohint.domain.errors import HintProviderError
from algohint.domain.models import (
    CodeReviewEntry,
    CodeReviewRequest,
    ProblemProgress,
    QuizAttempt,
    StoredQuizFeedback,
)
from algohint.domain.ports import (
    CodeReviewProvider,
    LearningLogRepository,
    ProblemRepository,
    ProfileRepository,
    ReviewHistoryRepository,
)

QUIZ_HISTORY_PAGE_SIZE = 20
CODE_REVIEW_HISTORY_PAGE_SIZE = 20
MAX_REVIEW_SOURCE_CHARS = 16_384


class CompletionRequiredError(PermissionError):
    """Raised when review content is requested before AC or give-up."""


class ReviewConsentRequiredError(PermissionError):
    """Raised before learner source is sent to an off-device review provider."""


class CodeReviewUnavailableError(RuntimeError):
    """Safe provider failure suitable for retry guidance in the UI."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class CompletionReviewService:
    """Release reviewed material without exposing answer keys before grading."""

    def __init__(
        self,
        problems: ProblemRepository,
        profiles: ProfileRepository,
        logs: LearningLogRepository,
        history: ReviewHistoryRepository,
        providers: Mapping[HintProviderId, CodeReviewProvider],
        safety: HintSafetyPolicy | None = None,
    ) -> None:
        self._problems = problems
        self._profiles = profiles
        self._logs = logs
        self._history = history
        self._providers = providers
        self._safety = safety or HintSafetyPolicy()

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

    def generate_code_review(
        self,
        profile_id: str,
        problem_id: str,
        source_code: str,
        *,
        cloud_consent: bool,
    ) -> CodeReviewReceipt:
        """Generate and persist feedback while never persisting the submitted source."""

        progress = self._progress(profile_id, problem_id)
        if not (progress.solved or progress.gave_up):
            raise CompletionRequiredError("ACまたはギブアップ後にコードをレビューできます。")
        if not source_code.strip():
            raise ValueError("レビューするPythonコードを入力してください。")
        if len(source_code) > MAX_REVIEW_SOURCE_CHARS:
            raise ValueError("レビューするコードは16KiB以内にしてください。")

        profile = self._profiles.get_profile(profile_id)
        provider = self._providers.get(profile.preferences.hint_provider)
        if provider is None:
            raise CodeReviewUnavailableError(
                ProviderFailureReason.NOT_CONFIGURED.value,
                "選択モデルはコードレビューに対応していません。",
            )
        availability = provider.availability()
        if availability.sends_data_off_device and not cloud_consent:
            raise ReviewConsentRequiredError("クラウド送信への同意が必要です。")
        if not availability.available:
            raise CodeReviewUnavailableError(
                ProviderFailureReason.NOT_CONFIGURED.value,
                availability.reason or "選択モデルを利用できません。",
            )

        problem = self._problems.get_problem(problem_id)
        completion_reason = (
            CompletionReason.FULL_AC if progress.solved else CompletionReason.GAVE_UP
        )
        request = CodeReviewRequest(
            learner_key=hashlib.sha256(profile_id.encode("utf-8")).hexdigest(),
            problem_id=problem.problem_id,
            title=problem.title,
            statement=problem.statement,
            constraints=problem.constraints,
            learning_goal=problem.learning_goal,
            tags=problem.tags,
            released_explanation=problem.explanation,
            source_code=source_code,
            completion_reason=completion_reason,
        )
        try:
            review = provider.generate_review(request)
        except HintProviderError as error:
            raise CodeReviewUnavailableError(
                error.reason_code.value,
                "コードレビューを生成できませんでした。設定を確認して再試行してください。",
            ) from error
        review_text = "\n".join(
            [
                review.algorithm_recap,
                *review.strengths,
                *(
                    f"{point.title}\n{point.feedback}"
                    for point in review.improvements
                ),
            ]
        )
        source_lines = {
            line.strip()
            for line in source_code.splitlines()
            if len(line.strip()) >= 12
        }
        repeats_source = any(line in review_text for line in source_lines)
        if not self._safety.is_safe(review_text) or repeats_source:
            raise CodeReviewUnavailableError(
                "unsafe_output",
                "提出コードを再掲する可能性があるため、レビューを保存・表示しませんでした。",
            )
        entry = CodeReviewEntry(
            reviewed_at=datetime.now(UTC),
            completion_reason=completion_reason,
            review=review,
        )
        quota = self._history.save_code_review(profile_id, problem_id, entry)
        return CodeReviewReceipt(entry=entry, quota=quota)

    def code_review_history(
        self,
        profile_id: str,
        problem_id: str,
        *,
        page: int = 0,
    ) -> CodeReviewHistoryPage:
        """Load persisted review text without ever reconstructing source code."""

        if page < 0:
            raise ValueError("page must not be negative")
        if self.view(profile_id, problem_id) is None:
            raise CompletionRequiredError("ACまたはギブアップ後に履歴を表示できます。")
        records = self._history.list_records(
            profile_id,
            problem_id,
            kind=ReviewHistoryKind.CODE_REVIEW.value,
            limit=CODE_REVIEW_HISTORY_PAGE_SIZE,
            offset=page * CODE_REVIEW_HISTORY_PAGE_SIZE,
        )
        return CodeReviewHistoryPage(
            entries=tuple(
                CodeReviewEntry.model_validate_json(record.payload_json)
                for record in records
            ),
            page=page,
            page_size=CODE_REVIEW_HISTORY_PAGE_SIZE,
            total_count=self._history.count_records(
                profile_id,
                problem_id,
                kind=ReviewHistoryKind.CODE_REVIEW.value,
            ),
            quota=self._history.quota_status(profile_id),
        )

    def _progress(self, profile_id: str, problem_id: str) -> ProblemProgress:
        return self._logs.load_log(profile_id).progress.get(
            problem_id,
            ProblemProgress(),
        )
