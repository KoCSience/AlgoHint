"""Learner-safe values returned from application services."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from algohint.domain.enums import JudgeStatus
from algohint.domain.models import (
    CodeReviewEntry,
    GeneratedHint,
    QuizAttempt,
    ReviewQuotaStatus,
    TutorSession,
)


@dataclass(frozen=True)
class LearnerProblemView:
    """Problem detail intentionally excluding hidden tests and model code."""

    problem_id: str
    title: str
    level: str
    tags: tuple[str, ...]
    learning_goal: str
    statement: str
    constraints: str
    input_format: str
    output_format: str
    samples: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SubmissionView:
    """Judge result filtered according to testcase visibility."""

    status: JudgeStatus
    passed_count: int
    total_count: int
    elapsed_ms: int | None
    message: str
    diagnostic: "LearnerDiagnostic | None" = None
    sample_input: str | None = None
    actual_output: str | None = None
    expected_output: str | None = None


@dataclass(frozen=True)
class LearnerDiagnostic:
    """Actionable failure detail that has crossed the hidden-case trust boundary."""

    status: JudgeStatus
    summary: str
    source_line: int | None = None
    source_column: int | None = None
    details: str | None = None
    redacted: bool = False
    diagnostic_id: str | None = None


@dataclass(frozen=True)
class LearningReport:
    """A compact report suitable for both Gradio and future UI adapters."""

    attempted_count: int
    solved_count: int
    correctness_rate: float
    average_hint_count: float
    average_attempt_count: float
    weak_tags: tuple[tuple[str, int], ...]
    recommended_problem_id: str | None


@dataclass(frozen=True)
class TutorReply:
    """One displayed hint plus the persisted, source-free conversation."""

    hint: GeneratedHint
    session: TutorSession
    source_omitted: bool = False


@dataclass(frozen=True)
class ExerciseSelection:
    """Resolved workspace location, deliberately separate from learning progress."""

    problem_id: str | None
    source: Literal["restored", "default", "explicit", "unavailable"]
    preference_repaired: bool = False
    persistence_warning: str | None = None


@dataclass(frozen=True)
class PublicQuizOption:
    """Learner-visible option without correctness metadata."""

    option_id: str
    text: str


@dataclass(frozen=True)
class PublicQuizQuestion:
    """Learner-visible question that cannot reveal its answer before grading."""

    question_id: str
    topic: str
    prompt: str
    options: tuple[PublicQuizOption, ...]


@dataclass(frozen=True)
class CompletionReviewView:
    """Completion-gated explanation and authored quiz."""

    explanation: str
    material_version: int
    questions: tuple[PublicQuizQuestion, ...]


@dataclass(frozen=True)
class QuizQuestionFeedback:
    """Post-submit detail with the selected and correct answer."""

    question_id: str
    prompt: str
    selected_option_id: str
    selected_text: str
    correct_option_id: str
    correct_text: str
    correct: bool
    explanation: str


@dataclass(frozen=True)
class QuizResult:
    """One deterministic grading result suitable for persistence in Phase 4."""

    material_version: int
    score: int
    total: int
    feedback: tuple[QuizQuestionFeedback, ...]
    attempted_at: datetime
    quota: ReviewQuotaStatus | None = None


@dataclass(frozen=True)
class QuizHistoryPage:
    """Newest-first persisted attempts plus pagination and quota state."""

    attempts: tuple[QuizAttempt, ...]
    page: int
    page_size: int
    total_count: int
    quota: ReviewQuotaStatus


@dataclass(frozen=True)
class CodeReviewReceipt:
    """Newly generated review plus the quota result of persisting it."""

    entry: CodeReviewEntry
    quota: ReviewQuotaStatus


@dataclass(frozen=True)
class CodeReviewHistoryPage:
    """Newest-first persisted source reviews."""

    entries: tuple[CodeReviewEntry, ...]
    page: int
    page_size: int
    total_count: int
    quota: ReviewQuotaStatus
