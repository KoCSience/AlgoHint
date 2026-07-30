"""Research evaluation execution and metrics remain bounded and auditable."""

import json
import shutil
from pathlib import Path

import pytest

from algohint.application.research_evaluation_service import (
    LiveResearchEvaluationUnavailableError,
    ResearchEvaluationService,
)
from algohint.cli import main
from algohint.domain.models import (
    ProfilePreferences,
    ResearchProviderRequest,
    ResearchResult,
    ResearchUsage,
)
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_knowledge_base_repository import (
    JsonKnowledgeBaseRepository,
)
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.json_research_evaluation_case_repository import (
    JsonResearchEvaluationCaseRepository,
)
from algohint.infrastructure.sqlite_research_evaluation_run_repository import (
    SqliteResearchEvaluationRunRepository,
)
from algohint.infrastructure.sqlite_research_history_repository import (
    SqliteResearchHistoryRepository,
)

PROJECT_ROOT = Path(__file__).parents[1]


def usage(*, available: bool = True) -> ResearchUsage:
    return ResearchUsage(
        available=available,
        state="available" if available else "hard_stopped",
        reason=None if available else "local_budget_exhausted",
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


def result(*, fallback: bool = False) -> ResearchResult:
    return ResearchResult(
        model="gemma-test",
        run_id="0123456789abcdef0123456789abcdef",
        text=(
            "静的ヒントへ切り替えます。"
            if fallback
            else "rangeの終点を小さい入力で確認しましょう。[S1]"
        ),
        citations=()
        if fallback
        else (
            {
                "citation_id": "S1",
                "title": "Python ranges",
                "url": "https://docs.python.org/3/library/stdtypes.html#ranges",
                "domain": "docs.python.org",
            },
        ),
        trace=("requested", "fallback")
        if fallback
        else ("requested", "planned", "searched", "completed"),
        search_requests=1,
        content_pages=2,
        cache_hits=0,
        elapsed_ms=100,
        fallback=fallback,
        usage=usage(),
    )


class FakeResearchProvider:
    """Record public benchmark requests without external I/O."""

    def __init__(self, *, available: bool = True) -> None:
        self._available = available
        self.requests: list[ResearchProviderRequest] = []

    def usage(self) -> ResearchUsage:
        return usage(available=self._available)

    def research(self, request: ResearchProviderRequest) -> ResearchResult:
        self.requests.append(request)
        return result()


def evaluation_service(
    content_paths: DataPaths,
    runtime_paths: DataPaths,
    history: SqliteResearchHistoryRepository,
) -> ResearchEvaluationService:
    return ResearchEvaluationService(
        JsonProblemRepository(content_paths),
        JsonKnowledgeBaseRepository(content_paths),
        JsonResearchEvaluationCaseRepository(content_paths),
        SqliteResearchEvaluationRunRepository(runtime_paths),
        history,
    )


def test_evaluation_separates_fixed_and_profile_quality(tmp_path) -> None:
    content_paths = DataPaths(PROJECT_ROOT / "data")
    runtime_paths = DataPaths(tmp_path / "runtime-data")
    profiles = JsonProfileRepository(runtime_paths)
    profile = profiles.create_profile("learner", ProfilePreferences())
    history = SqliteResearchHistoryRepository(runtime_paths, profiles)
    history.save(profile.profile_id, "l1_range_sum", "WA", result())
    history.save(profile.profile_id, "l1_range_sum", "TLE", result(fallback=True))
    runs = SqliteResearchEvaluationRunRepository(runtime_paths)
    range_case = next(
        case
        for case in JsonResearchEvaluationCaseRepository(
            content_paths
        ).list_cases()
        if case.case_id == "range-sum-wa"
    )
    runs.save(range_case, result())
    evaluation = evaluation_service(content_paths, runtime_paths, history)

    report = evaluation.evaluate(profile.profile_id)

    assert report.fixed_case_count == 15
    assert report.covered_problem_count == 5
    assert report.fixed_recorded_case_count == 1
    assert report.fixed_case_coverage_rate == pytest.approx(1 / 15)
    assert report.fixed_runs.recorded_run_count == 1
    assert report.fixed_runs.grounded_completion_rate == 1.0
    assert report.profile_runs.recorded_run_count == 2
    assert report.profile_runs.grounded_completion_rate == 0.5
    assert report.profile_runs.citation_integrity_rate == 0.5
    assert report.profile_runs.allowed_domain_rate == 1.0
    assert report.profile_runs.non_answer_rate == 1.0
    assert report.profile_runs.fallback_rate == 0.5


def test_live_evaluation_runs_only_unmeasured_selected_public_cases(tmp_path) -> None:
    content_paths = DataPaths(PROJECT_ROOT / "data")
    runtime_paths = DataPaths(tmp_path / "runtime-data")
    profiles = JsonProfileRepository(runtime_paths)
    history = SqliteResearchHistoryRepository(runtime_paths, profiles)
    evaluation = evaluation_service(content_paths, runtime_paths, history)
    provider = FakeResearchProvider()
    selected = ("two-values-wa", "range-sum-tle")

    first = evaluation.run_live(
        provider,
        max_cases=2,
        case_ids=selected,
    )
    skipped = evaluation.run_live(
        provider,
        max_cases=2,
        case_ids=selected,
    )
    rerun = evaluation.run_live(
        provider,
        max_cases=1,
        case_ids=("two-values-wa",),
        rerun=True,
    )

    assert tuple(run.case_id for run in first) == selected
    assert skipped == ()
    assert tuple(run.case_id for run in rerun) == ("two-values-wa",)
    assert [request.judge_status for request in provider.requests] == [
        "WA",
        "TLE",
        "WA",
    ]
    assert all(request.web_search_consent is True for request in provider.requests)
    assert all(not hasattr(request, "expected_focus") for request in provider.requests)
    assert runtime_paths.research_evaluation_runs_file.stat().st_mode & 0o777 == 0o600
    latest = SqliteResearchEvaluationRunRepository(runtime_paths).list_latest()
    assert {run.case_id for run in latest} == set(selected)


def test_live_evaluation_checks_usage_before_research(tmp_path) -> None:
    content_paths = DataPaths(PROJECT_ROOT / "data")
    runtime_paths = DataPaths(tmp_path / "runtime-data")
    profiles = JsonProfileRepository(runtime_paths)
    evaluation = evaluation_service(
        content_paths,
        runtime_paths,
        SqliteResearchHistoryRepository(runtime_paths, profiles),
    )
    provider = FakeResearchProvider(available=False)

    with pytest.raises(
        LiveResearchEvaluationUnavailableError,
        match="local_budget_exhausted",
    ):
        evaluation.run_live(provider)

    assert provider.requests == []
    assert not runtime_paths.research_evaluation_runs_file.exists()


def test_evaluate_cli_prints_nested_machine_readable_metrics(
    tmp_path,
    capsys,
) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(
        PROJECT_ROOT / "data",
        data_dir,
        ignore=shutil.ignore_patterns("runtime"),
    )

    main(["--data-dir", str(data_dir), "evaluate", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["fixed_case_count"] == 15
    assert payload["covered_problem_count"] == 5
    assert payload["fixed_recorded_case_count"] == 0
    assert payload["fixed_runs"]["recorded_run_count"] == 0
    assert payload["profile_runs"]["recorded_run_count"] == 0
    assert payload["executed_case_ids"] == []
    assert not (data_dir / "runtime" / "research_evaluation").exists()


def test_evaluate_cli_requires_explicit_live_cost_confirmation(tmp_path) -> None:
    with pytest.raises(
        SystemExit,
        match="requires --confirm-live-search-cost",
    ):
        main(
            [
                "--data-dir",
                str(tmp_path / "data"),
                "evaluate",
                "--run-live",
            ]
        )


def test_evaluate_cli_runs_one_confirmed_live_case_with_injected_provider(
    tmp_path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(
        PROJECT_ROOT / "data",
        data_dir,
        ignore=shutil.ignore_patterns("runtime"),
    )
    provider = FakeResearchProvider()
    monkeypatch.setenv("ALGOHINT_GEMMA_BACKEND", "transformers_http")
    monkeypatch.setenv("ALGOHINT_GEMMA_BASE_URL", "http://127.0.0.1:18080/v1")
    monkeypatch.setattr(
        "algohint.cli.GemmaResearchProvider",
        lambda *_args, **_kwargs: provider,
    )

    main(
        [
            "--data-dir",
            str(data_dir),
            "evaluate",
            "--run-live",
            "--confirm-live-search-cost",
            "--case-id",
            "two-values-wa",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["executed_case_ids"] == ["two-values-wa"]
    assert payload["fixed_recorded_case_count"] == 1
    assert payload["fixed_runs"]["grounded_completion_rate"] == 1.0
    assert [request.problem_id for request in provider.requests] == ["l0_two_values"]
