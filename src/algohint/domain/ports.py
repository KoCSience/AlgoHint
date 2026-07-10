"""Dependency inversion ports used by application services."""

from typing import Protocol

from algohint.domain.models import (
    JudgePolicy,
    JudgeResult,
    LLMRequest,
    LLMResponse,
    LearningLog,
    Problem,
    Profile,
    TestCase,
)


class ProblemRepository(Protocol):
    """Read self-authored content while keeping learner and teacher access explicit."""

    def list_problems(self) -> list[Problem]: ...

    def get_problem(self, problem_id: str) -> Problem: ...

    def get_tests(self, problem_id: str, include_hidden: bool) -> list[TestCase]: ...

    def get_model_solution(self, problem_id: str) -> str: ...

    def get_curriculum(self) -> list[dict[str, object]]: ...


class LearningLogRepository(Protocol):
    """Persist profiles and aggregate logs without storing learner source code."""

    def list_profiles(self) -> list[Profile]: ...

    def create_profile(self, display_name: str) -> Profile: ...

    def load_log(self, profile_id: str) -> LearningLog: ...

    def save_log(self, log: LearningLog) -> None: ...


class JudgeRunner(Protocol):
    """Run a submission against selected deterministic testcases."""

    def judge(self, source: str, cases: list[TestCase], policy: JudgePolicy) -> JudgeResult: ...


class LLMClient(Protocol):
    """Future hint-provider port; requests exclude source and private judge assets."""

    def generate(self, request: LLMRequest) -> LLMResponse: ...
