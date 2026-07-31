"""Immutable domain models.

Pydantic validation is used at the filesystem boundary so malformed teaching
content cannot silently reach the judge or learner UI.
"""

from datetime import date, datetime
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from algohint.domain.enums import (
    CodeReviewCategory,
    CompletionReason,
    CompareMode,
    HintCategory,
    HintProviderId,
    HintTrigger,
    JudgeStatus,
    PersonalizedQuizMode,
    ProviderFailureReason,
    QuizKind,
    QuizTopic,
    ReviewHistoryKind,
    SubmissionMode,
    TestVisibility,
    TutorRole,
)


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


class TutorMessage(FrozenModel):
    """One persisted question or displayed hint, never learner source code."""

    role: TutorRole
    text: str = Field(min_length=1, max_length=1_200)
    created_at: datetime
    trigger: HintTrigger | None = None
    provider: str | None = None
    model_name: str | None = None


class TutorSession(FrozenModel):
    """Bounded, problem-scoped conversation retained for one profile."""

    profile_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    messages: tuple[TutorMessage, ...] = Field(default=(), max_length=40)


class ProviderAvailability(FrozenModel):
    """Safe readiness metadata used by routing and the settings UI."""

    available: bool
    reason: str | None = None
    sends_data_off_device: bool = False


class ProviderDiagnostic(FrozenModel):
    """Provider reachability result with optional redacted development details."""

    healthy: bool
    provider: str
    model: str
    reason_code: ProviderFailureReason | None = None
    http_status: int | None = None
    retryable: bool = False
    exception_type: str | None = None
    debug_details: str | None = None


class HintGenerationRequest(FrozenModel):
    """Provider-neutral context containing learner-safe instructional data only."""

    learner_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    problem_id: str
    title: str
    statement: str
    constraints: str
    learning_goal: str
    tags: tuple[str, ...]
    authored_hint: Hint
    hint_count: int = Field(ge=0)
    trigger: HintTrigger
    question: str | None = Field(default=None, max_length=1_000)
    source_code: str | None = Field(default=None, max_length=16_384)
    judge_status: JudgeStatus | None = None
    diagnostic_summary: str | None = None
    diagnostic_details: str | None = Field(default=None, max_length=4_096)
    released_explanation: str | None = None
    history: tuple[TutorMessage, ...] = Field(default=(), max_length=40)


class GeneratedHint(FrozenModel):
    """Validated provider output ready for answer-leak inspection."""

    text: str = Field(min_length=1, max_length=1_200)
    category: HintCategory
    provider: str
    model_name: str
    used_fallback: bool = False
    fallback_reason: str | None = None


class ProfilePreferences(FrozenModel):
    """Persisted UI preferences that never prove progress or cloud consent.

    ``last_problem_id`` is only a best-effort navigation pointer. Completion
    gates must continue to use :class:`ProblemProgress`, because content can be
    removed and multiple browser tabs may overwrite this convenience state.
    """

    hint_provider: HintProviderId = HintProviderId.OPENAI
    personalized_quiz_mode: PersonalizedQuizMode = (
        PersonalizedQuizMode.ADAPTIVE_2_TO_5
    )
    last_problem_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9_-]+$",
    )


class Profile(FrozenModel):
    """A local, non-authenticated learner identity."""

    profile_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: str = Field(min_length=1, max_length=40)
    created_at: datetime
    preferences: ProfilePreferences = Field(default_factory=ProfilePreferences)
    is_development: bool = False


class ProblemProgress(FrozenModel):
    """Source-free aggregate kept separate from retained code history."""

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
    last_applied_submission_sequence: int = Field(default=0, ge=0)


class StoredLearnerDiagnostic(FrozenModel):
    """Learner-safe diagnostic persisted without private judge output."""

    status: JudgeStatus
    summary: str = Field(min_length=1, max_length=4_096)
    source_line: int | None = Field(default=None, ge=1)
    source_column: int | None = Field(default=None, ge=1)
    details: str | None = Field(default=None, max_length=4_096)
    redacted: bool = False
    diagnostic_id: str | None = Field(default=None, max_length=64)


class StoredExecutionResult(FrozenModel):
    """Latest learner-visible result for one code snapshot and judge mode."""

    mode: SubmissionMode
    executed_at: datetime
    status: JudgeStatus
    passed_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    elapsed_ms: int | None = Field(default=None, ge=0)
    message: str = Field(min_length=1, max_length=1_000)
    diagnostic: StoredLearnerDiagnostic | None = None
    sample_input: str | None = None
    actual_output: str | None = None
    expected_output: str | None = None


class CodeDraft(FrozenModel):
    """Mutable profile/problem workspace protected by optimistic revision checks."""

    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    source: str
    revision: int = Field(default=0, ge=0)
    updated_at: datetime | None = None


class CodeSnapshotSummary(FrozenModel):
    """Source-free history row safe to list before an explicit selection."""

    snapshot_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_bytes: int = Field(ge=0, le=1_048_576)
    first_executed_at: datetime
    last_executed_at: datetime
    sample_result: StoredExecutionResult | None = None
    full_result: StoredExecutionResult | None = None


class CodeSnapshot(CodeSnapshotSummary):
    """One distinct submitted program retained until explicit learner deletion."""

    source: str


class PendingProgressUpdate(FrozenModel):
    """Small crash-recovery event bridging SQLite history and aggregate JSON."""

    sequence: int = Field(ge=1)
    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    mode: SubmissionMode
    status: JudgeStatus


class QuizOption(FrozenModel):
    """One stable answer choice used by authored completion material."""

    option_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    text: str = Field(min_length=1, max_length=300)


class QuizQuestion(FrozenModel):
    """One authored question whose correct answer stays server-side until grading."""

    question_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    topic: QuizTopic
    prompt: str = Field(min_length=1, max_length=500)
    options: tuple[QuizOption, ...] = Field(min_length=3, max_length=4)
    correct_option_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    explanation: str = Field(min_length=1, max_length=800)

    def model_post_init(self, __context: object) -> None:
        option_ids = [option.option_id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError(f"Duplicate option ID in {self.question_id}")
        if self.correct_option_id not in option_ids:
            raise ValueError(f"Unknown correct option in {self.question_id}")


class ReviewMaterial(FrozenModel):
    """Exactly five reviewed questions covering the required learning dimensions."""

    version: int = Field(ge=1)
    questions: tuple[QuizQuestion, ...] = Field(min_length=5, max_length=5)

    def model_post_init(self, __context: object) -> None:
        question_ids = [question.question_id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Review material has duplicate question IDs")
        topics = {question.topic for question in self.questions}
        if topics != set(QuizTopic):
            raise ValueError("Review material must contain every quiz topic exactly once")


class StoredQuizFeedback(FrozenModel):
    """Snapshot that remains meaningful after authored material changes."""

    question_id: str
    prompt: str
    selected_option_id: str
    selected_text: str
    correct_option_id: str
    correct_text: str
    correct: bool
    explanation: str


class QuizAttempt(FrozenModel):
    """One immutable, detailed completion-quiz attempt."""

    attempted_at: datetime
    material_version: int = Field(ge=1)
    score: int = Field(ge=0, le=5)
    total: int = Field(default=5, ge=5, le=5)
    feedback: tuple[StoredQuizFeedback, ...] = Field(min_length=5, max_length=5)


class PersonalizedQuizQuestion(FrozenModel):
    """One server-identified AI question whose answer never crosses the pre-grade DTO."""

    question_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    focus: CodeReviewCategory
    prompt: str = Field(min_length=1, max_length=500)
    options: tuple[QuizOption, ...] = Field(min_length=3, max_length=4)
    correct_option_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    explanation: str = Field(min_length=1, max_length=800)

    def model_post_init(self, __context: object) -> None:
        option_ids = [option.option_id for option in self.options]
        option_texts = [option.text.strip() for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError(f"Duplicate option ID in {self.question_id}")
        if len(option_texts) != len(set(option_texts)):
            raise ValueError(f"Duplicate option text in {self.question_id}")
        if self.correct_option_id not in option_ids:
            raise ValueError(f"Unknown correct option in {self.question_id}")


class PersonalizedQuizSet(FrozenModel):
    """Persisted code-aware questions without retaining the source that produced them."""

    quiz_set_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    generated_at: datetime
    provider: str = Field(min_length=1, max_length=80)
    model_name: str = Field(min_length=1, max_length=200)
    mode: PersonalizedQuizMode
    questions: tuple[PersonalizedQuizQuestion, ...] = Field(
        min_length=2,
        max_length=5,
    )

    def model_post_init(self, __context: object) -> None:
        question_ids = [question.question_id for question in self.questions]
        prompts = [question.prompt.strip() for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Personalized quiz has duplicate question IDs")
        if len(prompts) != len(set(prompts)):
            raise ValueError("Personalized quiz has duplicate prompts")
        if self.mode is PersonalizedQuizMode.FIXED_3 and len(self.questions) != 3:
            raise ValueError("fixed_3 personalized quizzes must contain exactly three questions")


class PersonalizedQuizAttempt(FrozenModel):
    """One immutable grading snapshot for a generated code-aware quiz."""

    quiz_kind: QuizKind = QuizKind.AI_CODE
    quiz_set_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    attempted_at: datetime
    score: int = Field(ge=0, le=5)
    total: int = Field(ge=2, le=5)
    feedback: tuple[StoredQuizFeedback, ...] = Field(min_length=2, max_length=5)

    def model_post_init(self, __context: object) -> None:
        if self.total != len(self.feedback):
            raise ValueError("Personalized quiz total must match feedback length")
        if self.score != sum(item.correct for item in self.feedback):
            raise ValueError("Personalized quiz score must match feedback")


class ReviewQuotaStatus(FrozenModel):
    """Logical per-profile history usage after an atomic write or prune."""

    used_bytes: int = Field(ge=0)
    limit_bytes: int = Field(gt=0)
    warning: bool = False
    pruned_count: int = Field(default=0, ge=0)


class ReviewHistoryRecord(FrozenModel):
    """Validated storage envelope used by the SQLite history boundary."""

    record_id: int = Field(gt=0)
    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    kind: ReviewHistoryKind
    created_at: datetime
    payload_json: str = Field(min_length=2)


class CodeReviewRequest(FrozenModel):
    """Public, bounded context for a completion-only source review."""

    learner_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    title: str
    statement: str
    constraints: str
    learning_goal: str
    tags: tuple[str, ...]
    released_explanation: str
    source_code: str = Field(min_length=1, max_length=16_384)
    completion_reason: CompletionReason


class CodeReviewPoint(FrozenModel):
    """One prioritized improvement without replacement source code."""

    category: CodeReviewCategory
    title: str = Field(min_length=1, max_length=120)
    feedback: str = Field(min_length=1, max_length=500)


class GeneratedCodeReview(FrozenModel):
    """Structured provider output safe to persist after policy checks."""

    algorithm_recap: str = Field(min_length=1, max_length=600)
    strengths: tuple[
        Annotated[str, Field(min_length=1, max_length=300)],
        ...,
    ] = Field(default=(), max_length=3)
    improvements: tuple[CodeReviewPoint, ...] = Field(min_length=1, max_length=5)
    provider: str
    model_name: str


class PersonalizedQuizRequest(FrozenModel):
    """Bounded, public completion context for code-aware question generation."""

    learner_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    title: str
    statement: str
    constraints: str
    learning_goal: str
    tags: tuple[str, ...]
    source_code: str = Field(min_length=1, max_length=16_384)
    mode: PersonalizedQuizMode


class GeneratedPersonalizedQuizQuestion(FrozenModel):
    """Provider question before the application assigns grading identifiers."""

    focus: CodeReviewCategory
    prompt: str = Field(min_length=1, max_length=500)
    options: tuple[
        Annotated[str, Field(min_length=1, max_length=300)],
        ...,
    ] = Field(min_length=3, max_length=4)
    correct_option_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1, max_length=800)

    def model_post_init(self, __context: object) -> None:
        normalized = [option.strip() for option in self.options]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Generated personalized quiz options must be unique")
        if self.correct_option_index >= len(self.options):
            raise ValueError("Generated personalized quiz answer is outside options")


class GeneratedPersonalizedQuiz(FrozenModel):
    """Strict provider output ready for safety checks and server-owned IDs."""

    questions: tuple[GeneratedPersonalizedQuizQuestion, ...] = Field(
        min_length=2,
        max_length=5,
    )
    provider: str
    model_name: str

    def model_post_init(self, __context: object) -> None:
        prompts = [question.prompt.strip() for question in self.questions]
        if len(prompts) != len(set(prompts)):
            raise ValueError("Generated personalized quiz prompts must be unique")


class KnowledgeSource(FrozenModel):
    """One human-reviewed public source allowed for a problem's research."""

    title: str = Field(min_length=1, max_length=300)
    url: str = Field(pattern=r"^https://", max_length=2_048)
    domain: str = Field(
        pattern=r"^[a-z0-9.-]+$",
        min_length=1,
        max_length=253,
    )

    @model_validator(mode="after")
    def validate_url_domain(self) -> Self:
        """Require HTTPS and bind the reviewed domain to the parsed URL host."""

        parsed = urlsplit(self.url)
        host = (parsed.hostname or "").lower().rstrip(".")
        domain = self.domain.lower().rstrip(".")
        if parsed.scheme != "https" or not (
            host == domain or host.endswith("." + domain)
        ):
            raise ValueError("Knowledge source domain does not match its HTTPS URL")
        return self


class ProblemKnowledge(FrozenModel):
    """Versioned public knowledge used for static fallback and search planning."""

    version: int = Field(ge=1)
    reviewed_at: date
    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    public_summary: str = Field(min_length=1, max_length=2_000)
    concepts: tuple[str, ...] = Field(min_length=1, max_length=8)
    search_terms: tuple[str, ...] = Field(min_length=1, max_length=10)
    sources: tuple[KnowledgeSource, ...] = Field(min_length=1, max_length=8)


ResearchUsageState = Literal[
    "available",
    "warning",
    "hard_stopped",
    "unconfigured",
    "stale_pricing",
]


class ResearchUsage(FrozenModel):
    """Validated free-tier status returned by the private Gemma Server."""

    available: bool
    state: ResearchUsageState
    reason: str | None = Field(default=None, max_length=200)
    calendar_month: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}$")
    monthly_budget_usd: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$")
    warning_budget_usd: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$")
    calendar_month_cost_usd: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$")
    rolling_30_day_cost_usd: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$")
    calendar_month_searches: int = Field(ge=0)
    rolling_30_day_searches: int = Field(ge=0)
    today_searches: int = Field(ge=0)
    calendar_month_content_pages: int = Field(ge=0)
    remaining_searches: int = Field(ge=0)
    pricing_reviewed_at: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    pricing_valid_until: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class ResearchProviderRequest(FrozenModel):
    """Public-only request; no source, question, profile or hidden test can fit."""

    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    problem_title: str = Field(min_length=1, max_length=200)
    problem_summary: str = Field(min_length=1, max_length=2_000)
    language: Literal["Python"] = "Python"
    concepts: tuple[str, ...] = Field(min_length=1, max_length=8)
    search_terms: tuple[str, ...] = Field(min_length=1, max_length=10)
    allowed_domains: tuple[str, ...] = Field(min_length=1, max_length=8)
    judge_status: Literal["WA", "RE", "TLE", "CE", "AC", "GIVE_UP", "UNKNOWN"]
    hint_level: int = Field(ge=1, le=3)
    web_search_consent: Literal[True]
    client_request_id: str = Field(
        min_length=8,
        max_length=100,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )


class ResearchCitation(FrozenModel):
    """One source supporting a grounded research hint."""

    citation_id: str = Field(pattern=r"^S[1-9][0-9]*$")
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(pattern=r"^https://", max_length=2_048)
    domain: str = Field(min_length=1, max_length=253)

    @model_validator(mode="after")
    def validate_url_domain(self) -> Self:
        """Reject provider citations whose declared domain differs from the URL."""

        host = (urlsplit(self.url).hostname or "").lower().rstrip(".")
        if host != self.domain.lower().rstrip("."):
            raise ValueError("Research citation domain does not match its URL")
        return self


class ResearchResult(FrozenModel):
    """Grounded hint returned to the application after provider validation."""

    model: str = Field(min_length=1, max_length=200)
    run_id: str = Field(min_length=16, max_length=64)
    text: str = Field(min_length=1, max_length=4_000)
    citations: tuple[ResearchCitation, ...] = Field(max_length=2)
    trace: tuple[str, ...] = Field(min_length=1, max_length=20)
    search_requests: int = Field(ge=0, le=3)
    content_pages: int = Field(ge=0, le=12)
    cache_hits: int = Field(ge=0, le=6)
    elapsed_ms: int = Field(ge=0)
    fallback: bool
    usage: ResearchUsage


class ResearchHistoryEntry(FrozenModel):
    """Profile-scoped snapshot without raw Exa highlights or learner code."""

    entry_id: int = Field(gt=0)
    profile_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    created_at: datetime
    judge_status: str
    result: ResearchResult


class ResearchEvaluationCase(FrozenModel):
    """One fixed offline quality case; it contains no learner-specific data."""

    case_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    judge_status: Literal["WA", "TLE", "AC"]
    expected_focus: str = Field(min_length=1, max_length=200)


class ResearchEvaluationRun(FrozenModel):
    """One persisted live result for a fixed public evaluation case."""

    entry_id: int = Field(gt=0)
    case_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    problem_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    judge_status: Literal["WA", "TLE", "AC"]
    created_at: datetime
    result: ResearchResult


class CodeReviewEntry(FrozenModel):
    """Persisted review text; the submitted source itself remains absent."""

    reviewed_at: datetime
    completion_reason: CompletionReason
    review: GeneratedCodeReview
