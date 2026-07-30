"""Dependency inversion ports used by application services."""

from typing import Protocol

from algohint.domain.models import (
    CodeReviewEntry,
    CodeReviewRequest,
    GeneratedCodeReview,
    GeneratedHint,
    HintGenerationRequest,
    JudgePolicy,
    JudgeResult,
    LLMRequest,
    LLMResponse,
    LearningLog,
    PersonalizedQuizAttempt,
    PersonalizedQuizSet,
    Problem,
    Profile,
    ProfilePreferences,
    ProviderAvailability,
    QuizAttempt,
    ReviewHistoryRecord,
    ReviewMaterial,
    ReviewQuotaStatus,
    TestCase,
    TutorMessage,
    TutorSession,
)


class ProblemRepository(Protocol):
    """Read self-authored content while keeping learner and teacher access explicit."""

    def list_problems(self) -> list[Problem]: ...

    def get_problem(self, problem_id: str) -> Problem: ...

    def get_tests(self, problem_id: str, include_hidden: bool) -> list[TestCase]: ...

    def get_model_solution(self, problem_id: str) -> str: ...

    def get_curriculum(self) -> list[dict[str, object]]: ...

    def get_review_material(self, problem_id: str) -> ReviewMaterial: ...


class LearningLogRepository(Protocol):
    """Persist aggregate logs without storing learner source code."""

    def load_log(self, profile_id: str) -> LearningLog: ...

    def save_log(self, log: LearningLog) -> None: ...


class ProfileRepository(Protocol):
    """Persist local identities and preferences separately from learning metrics."""

    def list_profiles(self) -> list[Profile]: ...

    def get_profile(self, profile_id: str) -> Profile: ...

    def create_profile(self, display_name: str, preferences: ProfilePreferences) -> Profile: ...

    def save_profile(self, profile: Profile) -> None: ...


class TutorSessionRepository(Protocol):
    """Persist bounded conversations separately from aggregate learning logs."""

    def load(self, profile_id: str, problem_id: str) -> TutorSession: ...

    def save(self, session: TutorSession) -> None: ...

    def append(
        self,
        profile_id: str,
        problem_id: str,
        messages: tuple[TutorMessage, ...],
        *,
        limit: int,
    ) -> TutorSession: ...

    def clear(self, profile_id: str, problem_id: str) -> None: ...


class ReviewHistoryRepository(Protocol):
    """Persist bounded completion-review records separately from aggregates."""

    def save_quiz_attempt(
        self,
        profile_id: str,
        problem_id: str,
        attempt: QuizAttempt,
    ) -> ReviewQuotaStatus: ...

    def save_code_review(
        self,
        profile_id: str,
        problem_id: str,
        entry: CodeReviewEntry,
    ) -> ReviewQuotaStatus: ...

    def save_personalized_quiz(
        self,
        profile_id: str,
        problem_id: str,
        quiz: PersonalizedQuizSet,
    ) -> ReviewQuotaStatus: ...

    def save_personalized_quiz_attempt(
        self,
        profile_id: str,
        problem_id: str,
        attempt: PersonalizedQuizAttempt,
    ) -> ReviewQuotaStatus: ...

    def authored_quiz_completed(self, profile_id: str, problem_id: str) -> bool: ...

    def list_records(
        self,
        profile_id: str,
        problem_id: str,
        *,
        kind: str,
        limit: int,
        offset: int,
    ) -> tuple[ReviewHistoryRecord, ...]: ...

    def count_records(self, profile_id: str, problem_id: str, *, kind: str) -> int: ...

    def quota_status(self, profile_id: str) -> ReviewQuotaStatus: ...


class HintProvider(Protocol):
    """Generate one structured hint without judging or executing learner code."""

    def availability(self) -> ProviderAvailability: ...

    def generate(self, request: HintGenerationRequest) -> GeneratedHint: ...


class CodeReviewProvider(Protocol):
    """Generate completion feedback without receiving private judge assets."""

    def availability(self) -> ProviderAvailability: ...

    def generate_review(self, request: CodeReviewRequest) -> GeneratedCodeReview: ...


class LearningProvider(HintProvider, CodeReviewProvider, Protocol):
    """Provider supporting both isolated learning contracts."""


class JudgeRunner(Protocol):
    """Run a submission against selected deterministic testcases."""

    def judge(self, source: str, cases: list[TestCase], policy: JudgePolicy) -> JudgeResult: ...


class LLMClient(Protocol):
    """Future hint-provider port; requests exclude source and private judge assets."""

    def generate(self, request: LLMRequest) -> LLMResponse: ...
