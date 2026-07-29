"""Completion-gated authored review and deterministic quiz grading."""

from algohint.application.dto import (
    CompletionReviewView,
    PublicQuizOption,
    PublicQuizQuestion,
    QuizQuestionFeedback,
    QuizResult,
)
from algohint.domain.models import ProblemProgress
from algohint.domain.ports import LearningLogRepository, ProblemRepository


class CompletionRequiredError(PermissionError):
    """Raised when review content is requested before AC or give-up."""


class CompletionReviewService:
    """Release reviewed material without exposing answer keys before grading."""

    def __init__(
        self,
        problems: ProblemRepository,
        logs: LearningLogRepository,
    ) -> None:
        self._problems = problems
        self._logs = logs

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
        return QuizResult(
            material_version=material.version,
            score=score,
            total=len(feedback),
            feedback=tuple(feedback),
        )

    def _progress(self, profile_id: str, problem_id: str) -> ProblemProgress:
        return self._logs.load_log(profile_id).progress.get(
            problem_id,
            ProblemProgress(),
        )
