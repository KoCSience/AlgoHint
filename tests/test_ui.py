import json
from pathlib import Path

from algohint.application.explanation_service import ExplanationService
from algohint.application.exercise_selection_service import ExerciseSelectionService
from algohint.application.learning_report_service import LearningReportService
from algohint.application.problem_service import ProblemService
from algohint.application.profile_service import ProfileService
from algohint.application.submission_service import SubmissionService
from algohint.application.tutor_service import TutorService
from algohint.domain.enums import HintProviderId
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.json_tutor_session_repository import (
    JsonTutorSessionRepository,
)
from algohint.infrastructure.local_judge_runner import LocalJudgeRunner
from algohint.infrastructure.rule_based_hint_provider import RuleBasedHintProvider
from algohint.ui.gradio_app import build_app
from algohint.ui.gradio_workspace import _format_fallback_notice
from algohint.ui.view_models import ApplicationServices


def test_gradio_app_builds_without_teacher_tab_data(tmp_path: Path) -> None:
    problems = JsonProblemRepository(DataPaths(Path(__file__).parents[1] / "data"))
    paths = DataPaths(tmp_path / "runtime-data")
    profile_repository = JsonProfileRepository(paths)
    logs = JsonLearningLogRepository(paths, profile_repository)
    fallback = RuleBasedHintProvider()
    profile_service = ProfileService(profile_repository, logs, development_mode=True)
    problem_service = ProblemService(problems)
    app = build_app(
        ApplicationServices(
            profiles=profile_service,
            selections=ExerciseSelectionService(profile_service, problem_service),
            problems=problem_service,
            submissions=SubmissionService(problems, logs, LocalJudgeRunner()),
            tutor=TutorService(
                problems,
                profile_repository,
                logs,
                JsonTutorSessionRepository(paths),
                {HintProviderId.OPENAI: fallback},
                fallback,
            ),
            explanations=ExplanationService(problems, logs),
            reports=LearningReportService(problems, logs),
            teacher_repository=problems,
        ),
        teacher_mode=False,
        shared_mode=False,
    )

    assert app is not None
    config_text = json.dumps(app.get_config_file(), ensure_ascii=False, default=str)
    assert "開発テスト" in config_text
    assert "ヒントモデル" in config_text
    assert '"value": "l0_two_values"' in config_text
    assert "二つの数の合計" in config_text
    assert "わからない（次のヒント）" in config_text
    assert "実行結果からヒント" in config_text


def test_fallback_notice_is_actionable_without_raw_provider_data() -> None:
    notice = _format_fallback_notice("authentication_or_permission")

    assert "APIキー、権限、または課金設定" in notice
    assert "RuleBased" in notice
    assert "raw" not in notice


def test_client_lifecycle_fallback_notice_is_actionable() -> None:
    notice = _format_fallback_notice("client_lifecycle_error")

    assert "内部クライアント" in notice
    assert "更新または再起動" in notice
    assert "RuleBased" in notice
