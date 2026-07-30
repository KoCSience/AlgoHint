"""Learner-safe values returned from application services."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from algohint.domain.enums import CompletionReason, JudgeStatus
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
    newly_completed: bool = False
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
    give_up_count: int
    solve_after_hint_rate: float
    research_run_count: int
    research_grounded_rate: float
    average_research_latency_ms: float


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
class PublicPersonalizedQuiz:
    """Latest generated questions without correctness metadata."""

    quiz_set_id: str
    generated_at: datetime
    provider: str
    model_name: str
    questions: tuple[PublicQuizQuestion, ...]


@dataclass(frozen=True)
class PersonalizedQuizReceipt:
    """Safe generation result that does not expose answers or learner source."""

    quiz_set_id: str
    generated_at: datetime
    provider: str
    model_name: str
    question_count: int
    quota: ReviewQuotaStatus


@dataclass(frozen=True)
class PersonalizedQuizResult:
    """Deterministic grading result for one generated quiz set."""

    quiz_set_id: str
    score: int
    total: int
    feedback: tuple["QuizQuestionFeedback", ...]
    attempted_at: datetime
    quota: ReviewQuotaStatus


@dataclass(frozen=True)
class CompletionReviewView:
    """Completion state and answer-free authored questions."""

    completion_reason: CompletionReason
    authored_quiz_completed: bool
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


@dataclass(frozen=True)
class ResearchRunMetrics:
    """Comparable quality measures for one bounded set of Research runs."""

    recorded_run_count: int
    grounded_completion_rate: float
    citation_integrity_rate: float
    allowed_domain_rate: float
    non_answer_rate: float
    fallback_rate: float
    average_search_requests: float
    average_latency_ms: float
    cache_hit_rate: float


@dataclass(frozen=True)
class ResearchEvaluationReport:
    """Separate fixed benchmark evidence from optional learner-run evidence."""

    fixed_case_count: int
    covered_problem_count: int
    knowledge_source_count: int
    fixed_recorded_case_count: int
    fixed_case_coverage_rate: float
    fixed_runs: ResearchRunMetrics
    profile_runs: ResearchRunMetrics
