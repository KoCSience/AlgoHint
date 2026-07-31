"""Execute and measure the fixed grounded-Research evaluation dataset."""

from __future__ import annotations

import uuid

from algohint.application.dto import (
    ResearchEvaluationReport,
    ResearchRunMetrics,
)
from algohint.domain.models import (
    ProblemKnowledge,
    ResearchEvaluationCase,
    ResearchEvaluationRun,
    ResearchProviderRequest,
    ResearchResult,
)
from algohint.domain.ports import (
    KnowledgeBaseRepository,
    ProblemRepository,
    ResearchEvaluationCaseRepository,
    ResearchEvaluationRunRepository,
    ResearchHistoryRepository,
    ResearchProvider,
)

_ANSWER_LEAK_MARKERS = ("```", "完成コード", "正解コード", "そのまま提出")


class LiveResearchEvaluationUnavailableError(RuntimeError):
    """The server reported that a cost-controlled live run cannot start."""


class ResearchEvaluationService:
    """Run public fixed cases and report fixed and learner evidence separately."""

    def __init__(
        self,
        problems: ProblemRepository,
        knowledge: KnowledgeBaseRepository,
        cases: ResearchEvaluationCaseRepository,
        runs: ResearchEvaluationRunRepository,
        history: ResearchHistoryRepository,
    ) -> None:
        self._problems = problems
        self._knowledge = knowledge
        self._cases = cases
        self._runs = runs
        self._history = history

    def run_live(
        self,
        provider: ResearchProvider,
        *,
        max_cases: int = 1,
        case_ids: tuple[str, ...] = (),
        rerun: bool = False,
    ) -> tuple[ResearchEvaluationRun, ...]:
        """Run explicitly selected public cases through the real provider boundary.

        The CLI owns cost confirmation. This method additionally checks provider
        availability before the first case and relies on the Gemma Server ledger
        to reserve every Exa request before external I/O.
        """

        cases = self._validated_cases()
        if not 1 <= max_cases <= len(cases):
            raise ValueError("max_cases must be between 1 and the fixed case count")
        requested_ids = set(case_ids)
        known_ids = {case.case_id for case in cases}
        unknown_ids = requested_ids - known_ids
        if unknown_ids:
            raise ValueError(
                "unknown fixed research case IDs: " + ", ".join(sorted(unknown_ids))
            )
        completed_ids = {
            run.case_id for run in self._validated_fixed_runs(cases)
        }
        selected = tuple(
            case
            for case in cases
            if (not requested_ids or case.case_id in requested_ids)
            and (rerun or case.case_id not in completed_ids)
        )[:max_cases]
        if not selected:
            return ()
        usage = provider.usage()
        if not usage.available:
            raise LiveResearchEvaluationUnavailableError(
                usage.reason or usage.state
            )

        saved: list[ResearchEvaluationRun] = []
        for case in selected:
            problem = self._problems.get_problem(case.problem_id)
            knowledge = self._knowledge.get_knowledge(case.problem_id)
            request = ResearchProviderRequest(
                problem_id=problem.problem_id,
                problem_title=problem.title,
                problem_summary=knowledge.public_summary,
                concepts=knowledge.concepts,
                search_terms=knowledge.search_terms,
                allowed_domains=tuple(
                    dict.fromkeys(source.domain for source in knowledge.sources)
                ),
                judge_status=case.judge_status,
                hint_level=2,
                web_search_consent=True,
                client_request_id=f"evaluation-{uuid.uuid4().hex}",
            )
            result = provider.research(request)
            saved.append(self._runs.save(case, result))
        return tuple(saved)

    def evaluate(self, profile_id: str | None = None) -> ResearchEvaluationReport:
        """Compute transparent metrics from latest fixed and optional learner runs."""

        cases = self._validated_cases()
        problem_ids = {case.problem_id for case in cases}
        knowledge_by_problem = {
            problem_id: self._knowledge.get_knowledge(problem_id)
            for problem_id in problem_ids
        }
        fixed_runs = self._validated_fixed_runs(cases)
        profile_entries = (
            tuple(
                entry
                for problem_id in sorted(problem_ids)
                for entry in self._history.list(profile_id, problem_id, limit=100)
            )
            if profile_id is not None
            else ()
        )
        return ResearchEvaluationReport(
            fixed_case_count=len(cases),
            covered_problem_count=len(knowledge_by_problem),
            knowledge_source_count=sum(
                len(knowledge.sources) for knowledge in knowledge_by_problem.values()
            ),
            fixed_recorded_case_count=len(fixed_runs),
            fixed_case_coverage_rate=_ratio(len(fixed_runs), len(cases)),
            fixed_runs=_metrics(
                tuple((run.problem_id, run.result) for run in fixed_runs),
                knowledge_by_problem,
            ),
            profile_runs=_metrics(
                tuple(
                    (entry.problem_id, entry.result)
                    for entry in profile_entries
                ),
                knowledge_by_problem,
            ),
        )

    def _validated_cases(self) -> tuple[ResearchEvaluationCase, ...]:
        problems = self._problems.list_problems()
        problem_ids = {problem.problem_id for problem in problems}
        cases = self._cases.list_cases()
        if {case.problem_id for case in cases} != problem_ids:
            raise ValueError("fixed research cases must cover every problem")
        expected_matrix = {
            (problem_id, judge_status)
            for problem_id in problem_ids
            for judge_status in ("WA", "TLE", "AC")
        }
        actual_matrix = {(case.problem_id, case.judge_status) for case in cases}
        if actual_matrix != expected_matrix or len(actual_matrix) != len(cases):
            raise ValueError(
                "fixed research cases must cover WA, TLE and AC exactly once per problem"
            )
        return cases

    def _validated_fixed_runs(
        self,
        cases: tuple[ResearchEvaluationCase, ...],
    ) -> tuple[ResearchEvaluationRun, ...]:
        cases_by_id = {case.case_id: case for case in cases}
        runs = self._runs.list_latest()
        for run in runs:
            case = cases_by_id.get(run.case_id)
            if (
                case is None
                or run.problem_id != case.problem_id
                or run.judge_status != case.judge_status
            ):
                raise ValueError(
                    "stored evaluation run does not match the current fixed dataset"
                )
        return runs


def _metrics(
    evidence: tuple[tuple[str, ResearchResult], ...],
    knowledge_by_problem: dict[str, ProblemKnowledge],
) -> ResearchRunMetrics:
    """Calculate deterministic measures without an untracked model-as-judge."""

    total = len(evidence)
    grounded = sum(
        not result.fallback and result.trace[-1] == "completed"
        for _, result in evidence
    )
    citation_integrity = sum(
        bool(result.citations)
        and all(
            f"[{citation.citation_id}]" in result.text
            for citation in result.citations
        )
        for _, result in evidence
    )
    allowed_domains = 0
    for problem_id, result in evidence:
        sources = knowledge_by_problem[problem_id].sources
        if all(
            any(
                citation.domain == source.domain
                or citation.domain.endswith("." + source.domain)
                for source in sources
            )
            for citation in result.citations
        ):
            allowed_domains += 1
    non_answers = sum(
        not any(marker in result.text for marker in _ANSWER_LEAK_MARKERS)
        for _, result in evidence
    )
    searches = sum(result.search_requests for _, result in evidence)
    cache_hits = sum(result.cache_hits for _, result in evidence)
    return ResearchRunMetrics(
        recorded_run_count=total,
        grounded_completion_rate=_ratio(grounded, total),
        citation_integrity_rate=_ratio(citation_integrity, total),
        allowed_domain_rate=_ratio(allowed_domains, total),
        non_answer_rate=_ratio(non_answers, total),
        fallback_rate=_ratio(
            sum(result.fallback for _, result in evidence),
            total,
        ),
        average_search_requests=searches / total if total else 0.0,
        average_latency_ms=(
            sum(result.elapsed_ms for _, result in evidence) / total
            if total
            else 0.0
        ),
        cache_hit_rate=_ratio(cache_hits, searches + cache_hits),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0
