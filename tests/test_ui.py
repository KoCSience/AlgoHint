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
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.local_judge_runner import LocalJudgeRunner
from algohint.ui.gradio_app import build_app
from algohint.ui.view_models import ApplicationServices


def test_gradio_app_builds_without_teacher_tab_data(tmp_path: Path) -> None:
    problems = JsonProblemRepository(DataPaths(Path(__file__).parents[1] / "data"))
    paths = DataPaths(tmp_path / "runtime-data")
    profile_repository = JsonProfileRepository(paths)
    logs = JsonLearningLogRepository(paths, profile_repository)
    app = build_app(
        ApplicationServices(
            profiles=ProfileService(profile_repository, logs),
            problems=ProblemService(problems),
            submissions=SubmissionService(problems, logs, LocalJudgeRunner()),
            hints=HintService(problems, logs),
            explanations=ExplanationService(problems, logs),
            reports=LearningReportService(problems, logs),
            teacher_repository=problems,
        ),
        teacher_mode=False,
        shared_mode=False,
    )

    assert app is not None
