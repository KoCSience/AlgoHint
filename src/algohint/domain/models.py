"""Immutable domain models.

Pydantic validation is used at the filesystem boundary so malformed teaching
content cannot silently reach the judge or learner UI.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from algohint.domain.enums import CompareMode, HintCategory, JudgeStatus, TestVisibility


class FrozenModel(BaseModel):
    """Base model that prevents accidental mutation across UI callbacks."""

    model_config = ConfigDict(frozen=True)


class Hint(FrozenModel):
    """A deliberately partial prompt that advances one learning step."""

    level: int = Field(ge=1, le=6)
    category: HintCategory
    text: str = Field(min_length=1)
    leak_checked: bool = False


class TestCase(FrozenModel):
    """One deterministic input/output pair for LocalJudge."""

    case_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    input_text: str
    expected_output: str
    visibility: TestVisibility


class Problem(FrozenModel):
    """Self-authored exercise metadata and learner-safe teaching content."""

    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    title: str = Field(min_length=1)
    difficulty: str
    level: str = Field(pattern=r"^L[0-9]+$")
    tags: tuple[str, ...] = Field(min_length=1)
    learning_goal: str
    statement: str
    constraints: str
    input_format: str
    output_format: str
    hints: tuple[Hint, ...] = Field(min_length=5)
    explanation: str


class JudgePolicy(FrozenModel):
    """Resource and comparison policy for a local learning-only judge."""

    timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    memory_limit_mb: int = Field(default=256, ge=64, le=1024)
    output_limit_bytes: int = Field(default=16_384, ge=1_024, le=1_048_576)
    compare_mode: CompareMode = CompareMode.TRIM


class JudgeResult(FrozenModel):
    """Internal judge result; failed_case is never sent to learner DTOs directly."""

    status: JudgeStatus
    passed_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    elapsed_ms: int | None = Field(default=None, ge=0)
    stdout: str | None = None
    stderr: str | None = None
    failed_case: TestCase | None = None
    debug_message: str | None = None


class LLMRequest(FrozenModel):
    """Future-provider request containing only learner-safe hint context."""

    problem_id: str
    tags: tuple[str, ...]
    hint_count: int = Field(ge=0)
    judge_status: JudgeStatus | None = None


class LLMResponse(FrozenModel):
    """Provider-neutral generated text for a future, safety-checked hint."""

    text: str
    provider: str


class Profile(FrozenModel):
    """A local, non-authenticated learner identity."""

    profile_id: str
    display_name: str = Field(min_length=1, max_length=40)
    created_at: datetime


class ProblemProgress(FrozenModel):
    """Persisted aggregate only; submitted source is intentionally not retained."""

    attempt_count: int = Field(default=0, ge=0)
    failed_attempt_count: int = Field(default=0, ge=0)
    hint_count: int = Field(default=0, ge=0)
    solved: bool = False
    gave_up: bool = False
    last_status: JudgeStatus | None = None
    completed_at: datetime | None = None


class LearningLog(FrozenModel):
    """Profile-scoped learning history used for the progress report."""

    profile_id: str
    progress: dict[str, ProblemProgress] = Field(default_factory=dict)
