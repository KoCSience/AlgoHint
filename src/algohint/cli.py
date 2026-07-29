"""Command-line composition root for AlgoHint Coach."""

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

from algohint.application.config import AppConfig
from algohint.application.completion_review_service import CompletionReviewService
from algohint.application.explanation_service import ExplanationService
from algohint.application.exercise_selection_service import ExerciseSelectionService
from algohint.application.learning_report_service import LearningReportService
from algohint.application.problem_service import ProblemService
from algohint.application.profile_service import ProfileService
from algohint.application.submission_service import SubmissionService
from algohint.application.tutor_service import TutorService
from algohint.domain.enums import HintProviderId
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.hint_provider_factory import build_hint_providers
from algohint.infrastructure.gemini_hint_provider import GeminiHintProvider
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local-first algorithm practice coach")
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data"), help="Path to the content data directory"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host address for Gradio")
    parser.add_argument("--port", type=int, default=None, help="Optional Gradio server port")
    parser.add_argument(
        "--share", action="store_true", help="Create a Gradio share link for trusted Colab use"
    )
    parser.add_argument(
        "--teacher-mode", action="store_true", help="Show teacher-only test and solution views"
    )
    parser.add_argument(
        "--environment",
        choices=("production", "development"),
        default=None,
        help="Override ALGOHINT_ENV for profile and development behavior",
    )
    commands = parser.add_subparsers(dest="command")
    doctor = commands.add_parser(
        "doctor",
        help="Diagnose provider configuration without sending learner content",
    )
    doctor.add_argument(
        "--provider",
        choices=("gemini", "gemma"),
        required=True,
        help="Provider to diagnose",
    )
    doctor.add_argument(
        "--verbose",
        action="store_true",
        help="Show redacted exception details when running in development",
    )
    return parser


class _DiagnosableProvider(Protocol):
    """Provider surface used by doctor without coupling CLI to one SDK."""

    def diagnose(self, *, verbose: bool = False): ...


def _run_provider_doctor(
    label: str,
    provider: _DiagnosableProvider,
    *,
    verbose: bool = False,
    development_mode: bool = False,
) -> int:
    """Print one provider-neutral, secret-free diagnostic summary."""

    detailed = verbose and development_mode
    diagnostic = provider.diagnose(verbose=detailed)
    if diagnostic.healthy:
        print(
            f"{label}診断: OK "
            f"provider={diagnostic.provider} model={diagnostic.model}"
        )
        return 0
    reason = diagnostic.reason_code.value if diagnostic.reason_code else "unknown"
    status = diagnostic.http_status if diagnostic.http_status is not None else "-"
    exception_type = diagnostic.exception_type or "-"
    print(
        f"{label}診断: NG "
        f"provider={diagnostic.provider} model={diagnostic.model} "
        f"reason_code={reason} http_status={status} "
        f"retryable={str(diagnostic.retryable).lower()} "
        f"exception_type={exception_type}"
    )
    if verbose and not development_mode:
        print("詳細診断はdevelopmentでのみ有効です。ALGOHINT_ENV=developmentを設定してください。")
    elif diagnostic.debug_details is not None:
        print(f"{label}診断詳細（認証情報は伏字化済み）:")
        print(diagnostic.debug_details, end="" if diagnostic.debug_details.endswith("\n") else "\n")
    return 1


def _run_gemini_doctor(
    provider: GeminiHintProvider,
    *,
    verbose: bool = False,
    development_mode: bool = False,
) -> int:
    """Compatibility wrapper retained for focused Gemini doctor tests."""

    return _run_provider_doctor(
        "Gemini",
        provider,
        verbose=verbose,
        development_mode=development_mode,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Assemble concrete adapters and launch the Gradio application."""

    args = _parser().parse_args(argv)
    config = AppConfig.from_environment(args.environment)
    if args.command == "doctor":
        if args.provider == "gemini":
            provider: _DiagnosableProvider = GeminiHintProvider(
                config.gemini_model,
                timeout_seconds=config.cloud_timeout_seconds,
                development_mode=config.development_mode,
            )
            label = "Gemini"
        else:
            gemma_provider = build_hint_providers(config)[HintProviderId.GEMMA]
            if not hasattr(gemma_provider, "diagnose"):
                raise RuntimeError("configured Gemma provider does not support doctor")
            provider = cast(_DiagnosableProvider, gemma_provider)
            label = "Gemma"
        status = _run_provider_doctor(
            label,
            provider,
            verbose=args.verbose,
            development_mode=config.development_mode,
        )
        if status:
            raise SystemExit(status)
        return
    paths = DataPaths(args.data_dir)
    problems = JsonProblemRepository(paths)
    profile_repository = JsonProfileRepository(paths)
    logs = JsonLearningLogRepository(paths, profile_repository)
    tutor_sessions = JsonTutorSessionRepository(paths)
    providers = build_hint_providers(config)
    profile_service = ProfileService(
        profile_repository,
        logs,
        development_mode=config.development_mode,
        default_provider=config.default_hint_provider,
    )
    problem_service = ProblemService(problems)
    services = ApplicationServices(
        profiles=profile_service,
        selections=ExerciseSelectionService(profile_service, problem_service),
        reviews=CompletionReviewService(
            problems,
            profile_repository,
            logs,
            SqliteReviewHistoryRepository(paths, profile_repository),
            providers,
        ),
        problems=problem_service,
        submissions=SubmissionService(problems, logs, LocalJudgeRunner()),
        tutor=TutorService(
            problems,
            profile_repository,
            logs,
            tutor_sessions,
            providers,
            RuleBasedHintProvider(),
        ),
        explanations=ExplanationService(problems, logs),
        reports=LearningReportService(problems, logs),
        teacher_repository=problems,
    )
    if args.share:
        print(
            "Warning: --share exposes an interface that runs submitted code. Use only for trusted personal learning."
        )
    app = build_app(services, teacher_mode=args.teacher_mode, shared_mode=args.share)
    app.launch(server_name=args.host, server_port=args.port, share=args.share)
