"""Command-line composition root for AlgoHint Coach."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Protocol, cast

from algohint.application.config import AppConfig
from algohint.application.completion_review_service import CompletionReviewService
from algohint.application.completion_service import CompletionService
from algohint.application.code_workspace_service import CodeWorkspaceService
from algohint.application.exercise_selection_service import ExerciseSelectionService
from algohint.application.learning_report_service import LearningReportService
from algohint.application.problem_service import ProblemService
from algohint.application.profile_service import ProfileService
from algohint.application.research_service import GroundedResearchService
from algohint.application.research_evaluation_service import (
    LiveResearchEvaluationUnavailableError,
    ResearchEvaluationService,
)
from algohint.application.submission_service import SubmissionService
from algohint.application.tutor_service import TutorService
from algohint.domain.enums import (
    GemmaBackend,
    HintProviderId,
    ProviderFailureReason,
)
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.hint_provider_factory import build_hint_providers
from algohint.infrastructure.gemini_hint_provider import GeminiHintProvider
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_knowledge_base_repository import (
    JsonKnowledgeBaseRepository,
)
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_research_evaluation_case_repository import (
    JsonResearchEvaluationCaseRepository,
)
from algohint.infrastructure.json_tutor_session_repository import (
    JsonTutorSessionRepository,
)
from algohint.infrastructure.local_judge_runner import LocalJudgeRunner
from algohint.infrastructure.gemma_research_provider import (
    GemmaResearchProvider,
    ResearchProviderError,
)
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
from algohint.infrastructure.sqlite_research_evaluation_run_repository import (
    SqliteResearchEvaluationRunRepository,
)
from algohint.ui.gradio_app import build_app
from algohint.ui.view_models import ApplicationServices


def _evaluation_case_limit(value: str) -> int:
    """Parse a bounded live-evaluation count before any provider is created."""

    parsed = int(value)
    if not 1 <= parsed <= 15:
        raise argparse.ArgumentTypeError("max-cases must be between 1 and 15")
    return parsed


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
    doctor.add_argument(
        "--generation-probe",
        action="store_true",
        help="Run the authenticated server-owned Gemma generation probe",
    )
    evaluate = commands.add_parser(
        "evaluate",
        help="Evaluate fixed research coverage and optional recorded profile runs",
    )
    evaluate.add_argument(
        "--profile-id",
        default=None,
        help="Include the selected local profile's persisted Research runs",
    )
    evaluate.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable metrics",
    )
    evaluate.add_argument(
        "--run-live",
        action="store_true",
        help="Run unmeasured fixed cases through Gemma/Exa before reporting",
    )
    evaluate.add_argument(
        "--confirm-live-search-cost",
        action="store_true",
        help="Explicitly acknowledge that the live run consumes Exa credit",
    )
    evaluate.add_argument(
        "--max-cases",
        type=_evaluation_case_limit,
        default=1,
        help="Maximum live cases in this invocation (default: 1, maximum: 15)",
    )
    evaluate.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Restrict live execution to a fixed case ID; may be repeated",
    )
    evaluate.add_argument(
        "--rerun",
        action="store_true",
        help="Re-run selected cases even when saved evidence already exists",
    )
    return parser


class _DiagnosableProvider(Protocol):
    """Provider surface used by doctor without coupling CLI to one SDK."""

    def diagnose(self, *, verbose: bool = False): ...


class _GenerationProbeProvider(Protocol):
    """Gemma-only diagnostic extension that never accepts learner content."""

    def diagnose(
        self,
        *,
        verbose: bool = False,
        generation_probe: bool = False,
    ): ...


def _print_doctor_remediation(
    label: str,
    reason_code: object,
    provider_detail_code: str | None = None,
) -> None:
    """Print only stable, secret-free recovery guidance for known failures."""

    if (
        label == "Gemma"
        and reason_code is ProviderFailureReason.ENDPOINT_UNREACHABLE
    ):
        print(
            "Gemma診断の対処: Remoteはrun-ssh-stack.sh、Localは"
            "run-local-stack.shから再診断し、Serverと接続経路を確認してください。"
        )
    if label != "Gemma" or provider_detail_code is None:
        return
    remediation = {
        "gpu_memory_exhausted": "GPU使用量、token上限、memory配置を確認してServerを再起動してください。",
        "device_placement_failure": "固定Server releaseとdevice mapを確認してください。",
        "cuda_runtime_failure": "GPU driver、containerのGPU割当、Server logを確認してください。",
        "response_parsing_failure": "model revisionとTransformers parserの互換性を確認してください。",
        "unknown_generation_failure": "request IDに対応するServerのclosed logを確認してください。",
        "model_not_ready": "Serverのmodel load完了後にgeneration probeを再実行してください。",
    }.get(provider_detail_code)
    if remediation is not None:
        print(f"Gemma生成診断の対処: {remediation}")


def _run_provider_doctor(
    label: str,
    provider: _DiagnosableProvider,
    *,
    verbose: bool = False,
    development_mode: bool = False,
    generation_probe: bool = False,
) -> int:
    """Print one provider-neutral, secret-free diagnostic summary."""

    detailed = verbose and development_mode
    if generation_probe:
        diagnostic = cast(_GenerationProbeProvider, provider).diagnose(
            verbose=detailed,
            generation_probe=True,
        )
    else:
        diagnostic = provider.diagnose(verbose=detailed)
    if diagnostic.healthy:
        print(
            f"{label}診断: OK "
            f"provider={diagnostic.provider} model={diagnostic.model}"
            f"{' generation_probe=ready' if generation_probe else ''}"
        )
        return 0
    reason = diagnostic.reason_code.value if diagnostic.reason_code else "unknown"
    status = diagnostic.http_status if diagnostic.http_status is not None else "-"
    exception_type = diagnostic.exception_type or "-"
    provider_detail_code = diagnostic.provider_detail_code or "-"
    print(
        f"{label}診断: NG "
        f"provider={diagnostic.provider} model={diagnostic.model} "
        f"reason_code={reason} provider_detail_code={provider_detail_code} http_status={status} "
        f"retryable={str(diagnostic.retryable).lower()} "
        f"exception_type={exception_type}"
    )
    _print_doctor_remediation(
        label,
        diagnostic.reason_code,
        diagnostic.provider_detail_code,
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

    parser = _parser()
    args = parser.parse_args(argv)
    if (
        args.command == "doctor"
        and args.generation_probe
        and args.provider != "gemma"
    ):
        parser.error("--generation-probe is supported only with --provider gemma")
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
            generation_probe=args.generation_probe,
        )
        if status:
            raise SystemExit(status)
        return
    paths = DataPaths(args.data_dir)
    problems = JsonProblemRepository(paths)
    profile_repository = JsonProfileRepository(paths)
    logs = JsonLearningLogRepository(paths, profile_repository)
    research_history = SqliteResearchHistoryRepository(paths, profile_repository)
    knowledge = JsonKnowledgeBaseRepository(paths)
    if args.command == "evaluate":
        import json

        evaluation = ResearchEvaluationService(
            problems,
            knowledge,
            JsonResearchEvaluationCaseRepository(paths),
            SqliteResearchEvaluationRunRepository(paths),
            research_history,
        )
        executed_case_ids: tuple[str, ...] = ()
        if args.run_live:
            if not args.confirm_live_search_cost:
                raise SystemExit(
                    "--run-live requires --confirm-live-search-cost"
                )
            if (
                config.gemma_backend is not GemmaBackend.TRANSFORMERS_HTTP
                or not config.gemma_base_url
            ):
                raise SystemExit(
                    "live evaluation requires the transformers_http Gemma Server"
                )
            research_provider = GemmaResearchProvider(
                config.gemma_base_url,
                timeout_seconds=config.local_timeout_seconds,
            )
            try:
                executed = evaluation.run_live(
                    research_provider,
                    max_cases=args.max_cases,
                    case_ids=tuple(args.case_id),
                    rerun=args.rerun,
                )
            except (
                LiveResearchEvaluationUnavailableError,
                ResearchProviderError,
                ValueError,
            ) as error:
                raise SystemExit(
                    f"live research evaluation unavailable: {error}"
                ) from error
            executed_case_ids = tuple(run.case_id for run in executed)
        elif (
            args.confirm_live_search_cost
            or args.rerun
            or args.case_id
            or args.max_cases != 1
        ):
            raise SystemExit(
                "live evaluation options require --run-live"
            )
        report = evaluation.evaluate(args.profile_id)
        payload = {
            "executed_case_ids": executed_case_ids,
            **asdict(report),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            for name, value in payload.items():
                if isinstance(value, dict):
                    print(f"{name}:")
                    for metric, metric_value in value.items():
                        print(f"  {metric}: {metric_value}")
                else:
                    print(f"{name}: {value}")
        return
    tutor_sessions = JsonTutorSessionRepository(paths)
    code_history = SqliteCodeHistoryRepository(paths, profile_repository)
    providers = build_hint_providers(config)
    profile_service = ProfileService(
        profile_repository,
        logs,
        development_mode=config.development_mode,
        default_provider=config.default_hint_provider,
    )
    problem_service = ProblemService(problems)
    submission_service = SubmissionService(
        problems,
        logs,
        LocalJudgeRunner(),
        code_history,
    )
    for profile in profile_repository.list_profiles():
        submission_service.reconcile(profile.profile_id)
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
        submissions=submission_service,
        workspace=CodeWorkspaceService(code_history),
        tutor=TutorService(
            problems,
            profile_repository,
            logs,
            tutor_sessions,
            providers,
            RuleBasedHintProvider(),
        ),
        completions=CompletionService(logs),
        reports=LearningReportService(problems, logs, research_history),
        teacher_repository=problems,
        research=(
            GroundedResearchService(
                problems,
                knowledge,
                profile_repository,
                logs,
                GemmaResearchProvider(
                    config.gemma_base_url,
                    timeout_seconds=config.local_timeout_seconds,
                ),
                research_history,
            )
            if config.gemma_backend is GemmaBackend.TRANSFORMERS_HTTP
            and config.gemma_base_url
            else None
        ),
    )
    if args.share:
        print(
            "Warning: --share exposes an interface that runs submitted code. Use only for trusted personal learning."
        )
    app = build_app(services, teacher_mode=args.teacher_mode, shared_mode=args.share)
    app.launch(server_name=args.host, server_port=args.port, share=args.share)
