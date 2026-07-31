"""Best-effort restoration of the profile's last exercise workspace."""

from typing import Literal

from algohint.application.dto import ExerciseSelection
from algohint.application.problem_service import ProblemService
from algohint.application.profile_service import ProfileService


class ExerciseSelectionService:
    """Resolve and persist navigation without confusing it with learning progress."""

    def __init__(self, profiles: ProfileService, problems: ProblemService) -> None:
        self._profiles = profiles
        self._problems = problems

    def restore(self, profile_id: str | None) -> ExerciseSelection:
        """Restore a valid pointer, or repair it to the deterministic default."""

        available = self._problems.list_problems()
        default_id = self._default_problem_id(available)
        if default_id is None:
            return ExerciseSelection(problem_id=None, source="unavailable")
        if profile_id is None:
            return ExerciseSelection(problem_id=default_id, source="default")

        profile = self._profiles.get_profile(profile_id)
        valid_ids = {problem.problem_id for problem in available}
        candidate = profile.preferences.last_problem_id
        if candidate in valid_ids:
            return ExerciseSelection(problem_id=candidate, source="restored")
        return self._persist(
            profile_id,
            default_id,
            source="default",
            preference_repaired=candidate is not None,
        )

    def select(
        self,
        profile_id: str | None,
        problem_id: str,
    ) -> ExerciseSelection:
        """Validate explicit selection before making it the next restore target."""

        self._problems.get_learner_problem(problem_id)
        if profile_id is None:
            return ExerciseSelection(problem_id=problem_id, source="explicit")
        return self._persist(
            profile_id,
            problem_id,
            source="explicit",
            preference_repaired=False,
        )

    def _persist(
        self,
        profile_id: str,
        problem_id: str,
        *,
        source: Literal["default", "explicit"],
        preference_repaired: bool,
    ) -> ExerciseSelection:
        """Keep persistence failure non-fatal because this state is optional."""

        warning = None
        try:
            self._profiles.set_last_problem(profile_id, problem_id)
        except OSError:
            # The exercise remains usable even if the next-start convenience
            # pointer cannot be written to disk.
            warning = (
                "問題は表示できましたが、次回起動用の選択状態を保存できませんでした。"
            )
        return ExerciseSelection(
            problem_id=problem_id,
            source=source,
            preference_repaired=preference_repaired,
            persistence_warning=warning,
        )

    @staticmethod
    def _default_problem_id(problems) -> str | None:
        """Prefer authored L0 order, then retain repository order as fallback."""

        if not problems:
            return None
        first_l0 = next((problem for problem in problems if problem.level == "L0"), None)
        return (first_l0 or problems[0]).problem_id
