"""Transparent quality metrics for knowledge coverage and recorded research runs."""

from __future__ import annotations

from algohint.application.dto import ResearchEvaluationReport
from algohint.domain.ports import (
    KnowledgeBaseRepository,
    ProblemRepository,
    ResearchEvaluationCaseRepository,
    ResearchHistoryRepository,
)

_ANSWER_LEAK_MARKERS = ("```", "完成コード", "正解コード", "そのまま提出")


class ResearchEvaluationService:
    """Evaluate fixed coverage plus profile-scoped runtime evidence."""

    def __init__(
        self,
        problems: ProblemRepository,
        knowledge: KnowledgeBaseRepository,
        cases: ResearchEvaluationCaseRepository,
        history: ResearchHistoryRepository,
    ) -> None:
        self._problems = problems
        self._knowledge = knowledge
        self._cases = cases
        self._history = history

    def evaluate(self, profile_id: str | None = None) -> ResearchEvaluationReport:
        """Compute ratios directly from validated records without model judging."""

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
        knowledge_by_problem = {
            problem_id: self._knowledge.get_knowledge(problem_id)
            for problem_id in problem_ids
        }
        entries = (
            tuple(
                entry
                for problem_id in sorted(problem_ids)
                for entry in self._history.list(profile_id, problem_id, limit=100)
            )
            if profile_id is not None
            else ()
        )
        total = len(entries)
        grounded = sum(
            not entry.result.fallback and entry.result.trace[-1] == "completed"
            for entry in entries
        )
        citation_integrity = sum(
            bool(entry.result.citations)
            and all(
                f"[{citation.citation_id}]" in entry.result.text
                for citation in entry.result.citations
            )
            for entry in entries
        )
        allowed_domains = sum(
            all(
                any(
                    citation.domain == source.domain
                    or citation.domain.endswith("." + source.domain)
                    for source in knowledge_by_problem[entry.problem_id].sources
                )
                for citation in entry.result.citations
            )
            for entry in entries
        )
        non_answers = sum(
            not any(marker in entry.result.text for marker in _ANSWER_LEAK_MARKERS)
            for entry in entries
        )
        searches = sum(entry.result.search_requests for entry in entries)
        cache_hits = sum(entry.result.cache_hits for entry in entries)
        return ResearchEvaluationReport(
            fixed_case_count=len(cases),
            covered_problem_count=len(knowledge_by_problem),
            knowledge_source_count=sum(
                len(knowledge.sources) for knowledge in knowledge_by_problem.values()
            ),
            recorded_run_count=total,
            grounded_completion_rate=_ratio(grounded, total),
            citation_integrity_rate=_ratio(citation_integrity, total),
            allowed_domain_rate=_ratio(allowed_domains, total),
            non_answer_rate=_ratio(non_answers, total),
            fallback_rate=_ratio(
                sum(entry.result.fallback for entry in entries),
                total,
            ),
            average_search_requests=searches / total if total else 0.0,
            average_latency_ms=(
                sum(entry.result.elapsed_ms for entry in entries) / total
                if total
                else 0.0
            ),
            cache_hit_rate=_ratio(cache_hits, searches + cache_hits),
        )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0
