"""Closed vocabularies used to prevent ambiguous learning and judge states."""

from enum import StrEnum


class JudgeStatus(StrEnum):
    """The outcome of a code submission as determined by LocalJudge."""

    AC = "AC"
    WA = "WA"
    RE = "RE"
    TLE = "TLE"
    CE = "CE"
    IE = "IE"


class TestVisibility(StrEnum):
    """Whether a testcase may be revealed in the learner interface."""

    SAMPLE = "sample"
    HIDDEN = "hidden"


class HintCategory(StrEnum):
    """The learning purpose of each progressively disclosed hint."""

    UNDERSTANDING = "understanding"
    COMPLEXITY = "complexity"
    APPROACH = "approach"
    IMPLEMENTATION = "implementation"
    DEBUG = "debug"


class CompareMode(StrEnum):
    """Supported output comparisons; MVP intentionally exposes only trim."""

    TRIM = "trim"


class SubmissionMode(StrEnum):
    """Select public samples or the complete learner-safe judge flow."""

    SAMPLE = "sample"
    FULL = "full"


class HintProviderId(StrEnum):
    """Learner-selectable adaptive hint providers."""

    OPENAI = "openai"
    GEMMA = "gemma"
    GEMINI = "gemini"


class GemmaBackend(StrEnum):
    """Supported transport contracts for separately managed Gemma servers."""

    VLLM = "vllm"
    LLAMA_CPP = "llama_cpp"
    TRANSFORMERS_HTTP = "transformers_http"


class GemmaDeployment(StrEnum):
    """Data-location policy kept separate from the endpoint URL."""

    AUTO = "auto"
    LOCAL = "local"
    REMOTE = "remote"


class ProviderFailureReason(StrEnum):
    """Safe provider failure categories suitable for logs and learner UI."""

    NOT_CONFIGURED = "not_configured"
    INVALID_REQUEST = "invalid_request"
    AUTHENTICATION_OR_PERMISSION = "authentication_or_permission"
    MODEL_NOT_FOUND = "model_not_found"
    RATE_OR_QUOTA_EXCEEDED = "rate_or_quota_exceeded"
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    EMPTY_OR_BLOCKED_RESPONSE = "empty_or_blocked_response"
    INVALID_STRUCTURED_RESPONSE = "invalid_structured_response"
    CLIENT_LIFECYCLE_ERROR = "client_lifecycle_error"
    UNKNOWN_PROVIDER_ERROR = "unknown_provider_error"


class HintTrigger(StrEnum):
    """The learner action that requested adaptive coaching."""

    STUCK = "stuck"
    QUESTION = "question"
    JUDGE_RESULT = "judge_result"


class TutorRole(StrEnum):
    """Persisted roles in a problem-scoped tutoring conversation."""

    USER = "user"
    ASSISTANT = "assistant"


class QuizTopic(StrEnum):
    """Required review dimensions represented once in every problem quiz."""

    ALGORITHM = "algorithm"
    PROBLEM_FRAMING = "problem_framing"
    COMPLEXITY = "complexity"
    EDGE_CASES = "edge_cases"
    IMPLEMENTATION = "implementation"


class QuizKind(StrEnum):
    """Distinguish reviewed authored material from code-aware AI material."""

    AUTHORED = "authored"
    AI_CODE = "ai_code"


class PersonalizedQuizMode(StrEnum):
    """Control the bounded number of code-aware questions requested from AI."""

    ADAPTIVE_2_TO_5 = "adaptive_2_to_5"
    FIXED_3 = "fixed_3"


class ReviewHistoryKind(StrEnum):
    """Persisted completion-review record families sharing one quota."""

    QUIZ_ATTEMPT = "quiz_attempt"
    CODE_REVIEW = "code_review"
    AI_QUIZ_SET = "ai_quiz_set"
    AI_QUIZ_ATTEMPT = "ai_quiz_attempt"


class CompletionReason(StrEnum):
    """Authoritative event that made completion review available."""

    FULL_AC = "full_ac"
    GAVE_UP = "gave_up"


class CodeReviewCategory(StrEnum):
    """Bounded dimensions for actionable post-completion feedback."""

    CORRECTNESS = "correctness"
    EDGE_CASES = "edge_cases"
    COMPLEXITY = "complexity"
    READABILITY = "readability"
    MAINTAINABILITY = "maintainability"
