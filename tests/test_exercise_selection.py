from pathlib import Path

from algohint.application.exercise_selection_service import ExerciseSelectionService
from algohint.application.problem_service import ProblemService
from algohint.application.profile_service import ProfileService
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository

DATA_DIR = Path(__file__).parents[1] / "data"


def make_selection_service(tmp_path: Path):
    runtime_paths = DataPaths(tmp_path / "runtime-data")
    profile_repository = JsonProfileRepository(runtime_paths)
    logs = JsonLearningLogRepository(runtime_paths, profile_repository)
    profiles = ProfileService(profile_repository, logs)
    problems = ProblemService(JsonProblemRepository(DataPaths(DATA_DIR)))
    return ExerciseSelectionService(profiles, problems), profiles, profile_repository


def test_new_profile_defaults_to_l0_and_persists_navigation(tmp_path: Path) -> None:
    selections, profiles, repository = make_selection_service(tmp_path)
    profile = profiles.create_profile("学習者")

    selected = selections.restore(profile.profile_id)

    assert selected.problem_id == "l0_two_values"
    assert selected.source == "default"
    assert repository.get_profile(profile.profile_id).preferences.last_problem_id == (
        "l0_two_values"
    )


def test_explicit_selection_is_restored_per_profile(tmp_path: Path) -> None:
    selections, profiles, _ = make_selection_service(tmp_path)
    first = profiles.create_profile("一人目")
    second = profiles.create_profile("二人目")

    selections.select(first.profile_id, "l2_first_match")

    assert selections.restore(first.profile_id).problem_id == "l2_first_match"
    assert selections.restore(first.profile_id).source == "restored"
    assert selections.restore(second.profile_id).problem_id == "l0_two_values"


def test_stale_navigation_pointer_is_repaired_without_affecting_progress(
    tmp_path: Path,
) -> None:
    selections, profiles, repository = make_selection_service(tmp_path)
    profile = profiles.create_profile("学習者")
    stale = profile.model_copy(
        update={
            "preferences": profile.preferences.model_copy(
                update={"last_problem_id": "removed_problem"}
            )
        }
    )
    repository.save_profile(stale)

    selected = selections.restore(profile.profile_id)

    assert selected.problem_id == "l0_two_values"
    assert selected.preference_repaired
    assert repository.get_profile(profile.profile_id).preferences.last_problem_id == (
        "l0_two_values"
    )
