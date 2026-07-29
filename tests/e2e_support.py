"""Deterministic local app composition shared by API and browser E2E tests."""

import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from algohint.application.explanation_service import ExplanationService
from algohint.application.completion_review_service import CompletionReviewService
from algohint.application.exercise_selection_service import ExerciseSelectionService
from algohint.application.learning_report_service import LearningReportService
from algohint.application.problem_service import ProblemService
from algohint.application.profile_service import ProfileService
from algohint.application.submission_service import SubmissionService
from algohint.application.tutor_service import TutorService
from algohint.domain.enums import HintProviderId
from algohint.domain.models import (
    GeneratedHint,
    HintGenerationRequest,
    ProviderAvailability,
)
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.json_tutor_session_repository import (
    JsonTutorSessionRepository,
)
from algohint.infrastructure.local_judge_runner import LocalJudgeRunner
from algohint.infrastructure.rule_based_hint_provider import RuleBasedHintProvider
from algohint.infrastructure.sqlite_review_history_repository import (
    SqliteReviewHistoryRepository,
)
from algohint.ui.gradio_app import build_app
from algohint.ui.view_models import ApplicationServices

PROJECT_ROOT = Path(__file__).parents[1]
PROBLEM_ID = "l0_two_values"
PROFILE_ID = "development-test-profile"


class DeterministicGeminiProvider:
    """Return a safe adaptive hint while recording requests for E2E assertions."""

    def __init__(self) -> None:
        self.requests: list[HintGenerationRequest] = []

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(
            available=True,
            sends_data_off_device=True,
        )

    def generate(self, request: HintGenerationRequest) -> GeneratedHint:
        self.requests.append(request)
        return GeneratedHint(
            text="小さな入力を手計算し、それぞれの変数が何を表すか確認しましょう。",
            category=request.authored_hint.category,
            provider="gemini",
            model_name="gemini-e2e",
        )


def build_e2e_app(runtime_root: Path):
    """Build an isolated app with real repositories and a fake cloud boundary."""

    content_paths = DataPaths(PROJECT_ROOT / "data")
    runtime_paths = DataPaths(runtime_root)
    problems = JsonProblemRepository(content_paths)
    profiles = JsonProfileRepository(runtime_paths)
    logs = JsonLearningLogRepository(runtime_paths, profiles)
    sessions = JsonTutorSessionRepository(runtime_paths)
    provider = DeterministicGeminiProvider()
    profile_service = ProfileService(
        profiles,
        logs,
        development_mode=True,
        default_provider=HintProviderId.GEMINI,
    )
    problem_service = ProblemService(problems)
    services = ApplicationServices(
        profiles=profile_service,
        selections=ExerciseSelectionService(profile_service, problem_service),
        reviews=CompletionReviewService(
            problems,
            logs,
            SqliteReviewHistoryRepository(runtime_paths, profiles),
        ),
        problems=problem_service,
        submissions=SubmissionService(problems, logs, LocalJudgeRunner()),
        tutor=TutorService(
            problems,
            profiles,
            logs,
            sessions,
            {HintProviderId.GEMINI: provider},
            RuleBasedHintProvider(),
        ),
        explanations=ExplanationService(problems, logs),
        reports=LearningReportService(problems, logs),
        teacher_repository=problems,
    )
    return build_app(services, teacher_mode=False, shared_mode=False), provider


def _unused_local_port() -> int:
    """Choose an ephemeral loopback port instead of coupling tests to 7860."""

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def running_e2e_app(
    runtime_root: Path,
) -> Iterator[tuple[Any, str, DeterministicGeminiProvider]]:
    """Launch the queued app and guarantee server shutdown after each E2E test."""

    app, provider = build_e2e_app(runtime_root)
    _, local_url, _ = app.launch(
        server_name="127.0.0.1",
        server_port=_unused_local_port(),
        prevent_thread_lock=True,
        show_error=True,
        quiet=True,
    )
    try:
        yield app, local_url, provider
    finally:
        app.close()
