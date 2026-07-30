"""Aggregate local learning records into a presentation-neutral report."""

from collections import Counter

from algohint.application.dto import LearningReport
from algohint.domain.ports import (
    LearningLogRepository,
    ProblemRepository,
    ResearchHistoryRepository,
)


class LearningReportService:
    """Calculate simple, explainable metrics instead of opaque learner scoring."""

    def __init__(
        self,
        problems: ProblemRepository,
        logs: LearningLogRepository,
        research_history: ResearchHistoryRepository | None = None,
    ) -> None:
        self._problems = problems
        self._logs = logs
        self._research_history = research_history

    def report(self, profile_id: str) -> LearningReport:
        log = self._logs.load_log(profile_id)
        values = list(log.progress.values())
        attempted = sum(1 for value in values if value.attempt_count > 0 or value.gave_up)
        solved = sum(1 for value in values if value.solved)
        weak_tags: Counter[str] = Counter()
        for problem in self._problems.list_problems():
            progress = log.progress.get(problem.problem_id)
            if progress is not None and progress.failed_attempt_count:
                weak_tags.update({tag: progress.failed_attempt_count for tag in problem.tags})
        next_problem = next(
            (
                problem.problem_id
                for problem in self._problems.list_problems()
                if not log.progress.get(problem.problem_id, None)
                or not log.progress[problem.problem_id].solved
            ),
            None,
        )
        research_entries = (
            tuple(
                entry
                for problem in self._problems.list_problems()
                for entry in self._research_history.list(
                    profile_id,
                    problem.problem_id,
                    limit=100,
                )
            )
            if self._research_history is not None
            else ()
        )
        research_count = len(research_entries)
        return LearningReport(
            attempted_count=attempted,
            solved_count=solved,
            correctness_rate=solved / attempted if attempted else 0.0,
            average_hint_count=sum(value.hint_count for value in values) / attempted
            if attempted
            else 0.0,
            average_attempt_count=sum(value.attempt_count for value in values) / attempted
            if attempted
            else 0.0,
            weak_tags=tuple(weak_tags.most_common()),
            recommended_problem_id=next_problem,
            give_up_count=sum(value.gave_up for value in values),
            solve_after_hint_rate=(
                sum(value.solved and value.hint_count > 0 for value in values) / solved
                if solved
                else 0.0
            ),
            research_run_count=research_count,
            research_grounded_rate=(
                sum(not entry.result.fallback for entry in research_entries)
                / research_count
                if research_count
                else 0.0
            ),
            average_research_latency_ms=(
                sum(entry.result.elapsed_ms for entry in research_entries)
                / research_count
                if research_count
                else 0.0
            ),
        )
