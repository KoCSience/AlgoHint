"""Command-line composition root for AlgoHint Coach."""

import argparse
from pathlib import Path

from algohint.application.explanation_service import ExplanationService
from algohint.application.hint_service import HintService
from algohint.application.learning_report_service import LearningReportService
from algohint.application.problem_service import ProblemService
from algohint.application.profile_service import ProfileService
from algohint.application.submission_service import SubmissionService
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.local_judge_runner import LocalJudgeRunner
from algohint.ui.gradio_app import build_app
from algohint.ui.view_models import ApplicationServices


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local-first algorithm practice coach")
    parser.add_argument("--data-dir", type=Path, default=Path("data"), help="Path to the content data directory")
    parser.add_argument("--host", default="127.0.0.1", help="Host address for Gradio")
    parser.add_argument("--port", type=int, default=None, help="Optional Gradio server port")
    parser.add_argument("--share", action="store_true", help="Create a Gradio share link for trusted Colab use")
    parser.add_argument("--teacher-mode", action="store_true", help="Show teacher-only test and solution views")
    return parser


def main() -> None:
    """Assemble concrete adapters and launch the Gradio application."""

    args = _parser().parse_args()
    paths = DataPaths(args.data_dir)
    problems = JsonProblemRepository(paths)
    logs = JsonLearningLogRepository(paths)
    services = ApplicationServices(
        profiles=ProfileService(logs),
        problems=ProblemService(problems),
        submissions=SubmissionService(problems, logs, LocalJudgeRunner()),
        hints=HintService(problems, logs),
        explanations=ExplanationService(problems, logs),
        reports=LearningReportService(problems, logs),
        teacher_repository=problems,
    )
    if args.share:
        print("Warning: --share exposes an interface that runs submitted code. Use only for trusted personal learning.")
    app = build_app(services, teacher_mode=args.teacher_mode, shared_mode=args.share)
    app.launch(server_name=args.host, server_port=args.port, share=args.share)
