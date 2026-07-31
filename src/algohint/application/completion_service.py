"""Explicit non-Judge exercise completion transitions."""

from datetime import UTC, datetime

from algohint.domain.models import ProblemProgress
from algohint.domain.ports import LearningLogRepository


class CompletionService:
    """Record give-up without owning post-completion material access."""

    def __init__(self, logs: LearningLogRepository) -> None:
        self._logs = logs

    def give_up(self, profile_id: str, problem_id: str) -> bool:
        """Mark surrender and report whether this is the first such transition."""

        log = self._logs.load_log(profile_id)
        current = log.progress.get(problem_id, ProblemProgress())
        if current.solved or current.gave_up:
            return False
        updated = current.model_copy(update={"gave_up": True, "completed_at": datetime.now(UTC)})
        self._logs.save_log(
            log.model_copy(update={"progress": {**log.progress, problem_id: updated}})
        )
        return True
