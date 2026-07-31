"""Deterministic local app composition shared by API and browser E2E tests."""

import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from algohint.application.completion_service import CompletionService
from algohint.application.completion_review_service import CompletionReviewService
from algohint.application.exercise_selection_service import ExerciseSelectionService
from algohint.application.learning_report_service import LearningReportService
from algohint.application.problem_service import ProblemService
from algohint.application.profile_service import ProfileService
from algohint.application.research_service import GroundedResearchService
from algohint.application.submission_service import SubmissionService
from algohint.application.tutor_service import TutorService
from algohint.domain.enums import CodeReviewCategory, HintProviderId
from algohint.domain.models import (
    CodeReviewPoint,
    CodeReviewRequest,
    GeneratedCodeReview,
    GeneratedHint,
    GeneratedPersonalizedQuiz,
    GeneratedPersonalizedQuizQuestion,
    HintGenerationRequest,
    PersonalizedQuizRequest,
    ProviderAvailability,
    ResearchProviderRequest,
    ResearchResult,
    ResearchUsage,
)
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_knowledge_base_repository import (
    JsonKnowledgeBaseRepository,
)
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
from algohint.infrastructure.sqlite_code_history_repository import (
    SqliteCodeHistoryRepository,
)
from algohint.infrastructure.sqlite_research_history_repository import (
    SqliteResearchHistoryRepository,
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
        self.review_requests: list[CodeReviewRequest] = []
        self.quiz_requests: list[PersonalizedQuizRequest] = []
        self.research_requests: list[ResearchProviderRequest] = []

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

    def generate_review(self, request: CodeReviewRequest) -> GeneratedCodeReview:
        """Return deterministic completion feedback without retaining source text."""

        self.review_requests.append(request)
        return GeneratedCodeReview(
            algorithm_recap="入力を整数へ変換し、必要な演算だけを行う問題です。",
            strengths=("入出力の流れが簡潔です。",),
            improvements=(
                CodeReviewPoint(
                    category=CodeReviewCategory.READABILITY,
                    title="変数名の意図",
                    feedback="問題文の値との対応が伝わる名前を維持しましょう。",
                ),
            ),
            provider="gemini",
            model_name="gemini-e2e",
        )

    def generate_quiz(
        self,
        request: PersonalizedQuizRequest,
    ) -> GeneratedPersonalizedQuiz:
        """Return bounded code-aware questions without copying submitted source."""

        self.quiz_requests.append(request)
        question_count = 3 if request.mode.value == "fixed_3" else 2
        questions = tuple(
            GeneratedPersonalizedQuizQuestion(
                focus=(
                    CodeReviewCategory.CORRECTNESS
                    if index == 0
                    else CodeReviewCategory.MAINTAINABILITY
                ),
                prompt=f"コード別の学習確認 {index + 1}",
                options=("適切な選択肢", "不適切な選択肢", "別の不適切な選択肢"),
                correct_option_index=0,
                explanation="現在の実装を学習観点から確認するための解説です。",
            )
            for index in range(question_count)
        )
        return GeneratedPersonalizedQuiz(
            questions=questions,
            provider="gemini",
            model_name="gemini-e2e",
        )

    def usage(self) -> ResearchUsage:
        """Return a deterministic local-budget snapshot for UI E2E tests."""

        return ResearchUsage(
            available=True,
            state="available",
            calendar_month="2026-07",
            monthly_budget_usd="9",
            warning_budget_usd="7",
            calendar_month_cost_usd="0.009",
            rolling_30_day_cost_usd="0.009",
            calendar_month_searches=1,
            rolling_30_day_searches=1,
            today_searches=1,
            calendar_month_content_pages=2,
            remaining_searches=999,
            pricing_reviewed_at="2026-07-30",
            pricing_valid_until="2026-10-28",
        )

    def research(self, request: ResearchProviderRequest) -> ResearchResult:
        """Return one cited response while retaining only the public request."""

        self.research_requests.append(request)
        return ResearchResult(
            model="gemma-e2e",
            run_id="0123456789abcdef0123456789abcdef",
            text="入力を数値に変換する理由を確認しましょう。[S1]",
            citations=(
                {
                    "citation_id": "S1",
                    "title": "Python input",
                    "url": "https://docs.python.org/3/library/functions.html#input",
                    "domain": "docs.python.org",
                },
            ),
            trace=("requested", "planned", "searched", "completed"),
            search_requests=1,
            content_pages=2,
            cache_hits=0,
            elapsed_ms=10,
            fallback=False,
            usage=self.usage(),
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
    research_history = SqliteResearchHistoryRepository(runtime_paths, profiles)
    code_history = SqliteCodeHistoryRepository(runtime_paths, profiles)
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
            profiles,
            logs,
            SqliteReviewHistoryRepository(runtime_paths, profiles),
            {HintProviderId.GEMINI: provider},
        ),
        problems=problem_service,
        submissions=SubmissionService(problems, logs, LocalJudgeRunner(), code_history),
        tutor=TutorService(
            problems,
            profiles,
            logs,
            sessions,
            {HintProviderId.GEMINI: provider},
            RuleBasedHintProvider(),
        ),
        completions=CompletionService(logs),
        reports=LearningReportService(problems, logs, research_history),
        teacher_repository=problems,
        research=GroundedResearchService(
            problems,
            JsonKnowledgeBaseRepository(content_paths),
            profiles,
            logs,
            provider,
            research_history,
        ),
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
