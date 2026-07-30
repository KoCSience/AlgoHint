"""Research evaluation metrics remain deterministic and externally auditable."""

import json
from pathlib import Path

from algohint.application.research_evaluation_service import ResearchEvaluationService
from algohint.cli import main
from algohint.domain.models import ProfilePreferences, ResearchResult, ResearchUsage
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_knowledge_base_repository import (
    JsonKnowledgeBaseRepository,
)
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.json_research_evaluation_case_repository import (
    JsonResearchEvaluationCaseRepository,
)
from algohint.infrastructure.sqlite_research_history_repository import (
    SqliteResearchHistoryRepository,
)

PROJECT_ROOT = Path(__file__).parents[1]


def result(*, fallback: bool = False) -> ResearchResult:
    usage = ResearchUsage(
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
        usage=usage,
    )


def test_evaluation_combines_fixed_coverage_and_recorded_quality(tmp_path) -> None:
    content_paths = DataPaths(PROJECT_ROOT / "data")
    runtime_paths = DataPaths(tmp_path / "runtime-data")
    profiles = JsonProfileRepository(runtime_paths)
    profile = profiles.create_profile("learner", ProfilePreferences())
    history = SqliteResearchHistoryRepository(runtime_paths, profiles)
    history.save(profile.profile_id, "l1_range_sum", "WA", result())
    history.save(profile.profile_id, "l1_range_sum", "TLE", result(fallback=True))
    evaluation = ResearchEvaluationService(
        JsonProblemRepository(content_paths),
        JsonKnowledgeBaseRepository(content_paths),
        JsonResearchEvaluationCaseRepository(content_paths),
        history,
    )

    report = evaluation.evaluate(profile.profile_id)

    assert report.fixed_case_count == 15
    assert report.covered_problem_count == 5
    assert report.recorded_run_count == 2
    assert report.grounded_completion_rate == 0.5
    assert report.citation_integrity_rate == 0.5
    assert report.allowed_domain_rate == 1.0
    assert report.non_answer_rate == 1.0
    assert report.fallback_rate == 0.5


def test_evaluate_cli_prints_machine_readable_fixed_metrics(capsys) -> None:
    main(["--data-dir", str(PROJECT_ROOT / "data"), "evaluate", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["fixed_case_count"] == 15
    assert payload["covered_problem_count"] == 5
    assert payload["recorded_run_count"] == 0
