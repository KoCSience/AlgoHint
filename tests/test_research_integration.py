"""Grounded research crosses only reviewed public data and stays profile-scoped."""

from pathlib import Path

import httpx
import pytest

from algohint.application.research_service import (
    GroundedResearchService,
    ResearchConsentRequiredError,
)
from algohint.domain.models import (
    KnowledgeSource,
    ProfilePreferences,
    ResearchCitation,
    ResearchProviderRequest,
    ResearchResult,
    ResearchUsage,
)
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.gemma_research_provider import GemmaResearchProvider
from algohint.infrastructure.json_knowledge_base_repository import (
    JsonKnowledgeBaseRepository,
)
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.sqlite_research_history_repository import (
    SqliteResearchHistoryRepository,
)

PROJECT_ROOT = Path(__file__).parents[1]


def usage() -> ResearchUsage:
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


def result() -> ResearchResult:
    return ResearchResult(
        model="google/gemma-test",
        run_id="0123456789abcdef0123456789abcdef",
        text="境界を小さい入力で確認しましょう。[S1]",
        citations=(
            {
                "citation_id": "S1",
                "title": "Python range",
                "url": "https://docs.python.org/3/library/stdtypes.html#ranges",
                "domain": "docs.python.org",
            },
        ),
        trace=("requested", "planned", "searched", "completed"),
        search_requests=1,
        content_pages=2,
        cache_hits=0,
        elapsed_ms=10,
        fallback=False,
        usage=usage(),
    )


class FakeResearchProvider:
    def __init__(self) -> None:
        self.requests: list[ResearchProviderRequest] = []

    def usage(self) -> ResearchUsage:
        return usage()

    def research(self, request: ResearchProviderRequest) -> ResearchResult:
        self.requests.append(request)
        return result()


def test_application_sends_reviewed_public_context_and_persists_history(tmp_path) -> None:
    content_paths = DataPaths(PROJECT_ROOT / "data")
    runtime_paths = DataPaths(tmp_path / "runtime-data")
    problems = JsonProblemRepository(content_paths)
    profiles = JsonProfileRepository(runtime_paths)
    profile = profiles.create_profile("learner", ProfilePreferences())
    logs = JsonLearningLogRepository(runtime_paths, profiles)
    provider = FakeResearchProvider()
    history = SqliteResearchHistoryRepository(runtime_paths, profiles)
    service = GroundedResearchService(
        problems,
        JsonKnowledgeBaseRepository(content_paths),
        profiles,
        logs,
        provider,
        history,
    )

    with pytest.raises(ResearchConsentRequiredError):
        service.research(profile.profile_id, "l1_range_sum", consent=False)
    response = service.research(profile.profile_id, "l1_range_sum", consent=True)

    request_payload = provider.requests[0].model_dump()
    assert response.run_id == result().run_id
    assert request_payload["problem_summary"].startswith("正の整数N")
    assert set(request_payload) == {
        "problem_id",
        "problem_title",
        "problem_summary",
        "language",
        "concepts",
        "search_terms",
        "allowed_domains",
        "judge_status",
        "hint_level",
        "web_search_consent",
        "client_request_id",
    }
    assert "source" not in request_payload
    assert "question" not in request_payload
    assert "profile" not in request_payload
    saved = service.history(profile.profile_id, "l1_range_sum")
    assert len(saved) == 1
    assert saved[0].result.citations[0].domain == "docs.python.org"


def test_gemma_research_provider_uses_bearer_and_exact_public_payload(monkeypatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=result().model_dump(mode="json"))

    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", "local-test-secret")
    provider = GemmaResearchProvider(
        "http://127.0.0.1:18080/v1",
        timeout_seconds=10,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    request = ResearchProviderRequest(
        problem_id="l1_range_sum",
        problem_title="1からNまでの合計",
        problem_summary="公開問題要約",
        concepts=("range",),
        search_terms=("Python range",),
        allowed_domains=("docs.python.org",),
        judge_status="WA",
        hint_level=2,
        web_search_consent=True,
        client_request_id="request-1234",
    )

    received = provider.research(request)

    assert received.run_id == result().run_id
    assert seen[0].url.path == "/v1/research"
    assert seen[0].headers["authorization"] == "Bearer local-test-secret"
    assert b"source_code" not in seen[0].content
    assert b"profile_id" not in seen[0].content


@pytest.mark.parametrize(
    "problem_id",
    [
        "l0_two_values",
        "l1_value_class",
        "l1_range_sum",
        "l2_first_match",
        "l3_frequency_count",
    ],
)
def test_every_problem_has_reviewed_knowledge(problem_id: str) -> None:
    repository = JsonKnowledgeBaseRepository(DataPaths(PROJECT_ROOT / "data"))

    knowledge = repository.get_knowledge(problem_id)

    assert knowledge.problem_id == problem_id
    assert knowledge.sources
    assert all(source.url.startswith("https://") for source in knowledge.sources)


@pytest.mark.parametrize(
    ("url", "domain"),
    [
        ("https://attacker.example/?next=docs.python.org", "docs.python.org"),
        ("http://docs.python.org/3/", "docs.python.org"),
    ],
)
def test_knowledge_source_rejects_untrusted_or_non_https_url(
    url: str,
    domain: str,
) -> None:
    with pytest.raises(ValueError):
        KnowledgeSource(title="Untrusted", url=url, domain=domain)


def test_research_citation_rejects_spoofed_domain() -> None:
    with pytest.raises(ValueError, match="domain does not match"):
        ResearchCitation(
            citation_id="S1",
            title="Spoofed",
            url="https://attacker.example/resource",
            domain="docs.python.org",
        )
