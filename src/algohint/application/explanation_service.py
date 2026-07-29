"""Explanation gating use cases."""

from datetime import UTC, datetime

from algohint.domain.models import ProblemProgress
from algohint.domain.ports import LearningLogRepository, ProblemRepository


class ExplanationService:
    """Protect productive struggle by releasing explanations only at completion."""

    def __init__(self, problems: ProblemRepository, logs: LearningLogRepository) -> None:
        self._problems = problems
        self._logs = logs

    def give_up(self, profile_id: str, problem_id: str) -> None:
        log = self._logs.load_log(profile_id)
        current = log.progress.get(problem_id, ProblemProgress())
        updated = current.model_copy(update={"gave_up": True, "completed_at": datetime.now(UTC)})
        self._logs.save_log(
            log.model_copy(update={"progress": {**log.progress, problem_id: updated}})
        )

    def get_explanation(self, profile_id: str, problem_id: str) -> str | None:
        progress = self._logs.load_log(profile_id).progress.get(problem_id, ProblemProgress())
        if not (progress.solved or progress.gave_up):
            return None
        return self._problems.get_problem(problem_id).explanation
