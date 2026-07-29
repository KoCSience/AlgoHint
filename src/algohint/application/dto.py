"""Learner-safe values returned from application services."""

from dataclasses import dataclass
from typing import Literal

from algohint.domain.enums import JudgeStatus
from algohint.domain.models import GeneratedHint, TutorSession


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
