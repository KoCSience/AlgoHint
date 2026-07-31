import json
from datetime import UTC, datetime
from pathlib import Path

from algohint.application.profile_service import (
    DEVELOPMENT_PROFILE_ID,
    ProfileService,
)
from algohint.domain.enums import HintProviderId
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository


def make_profile_service(
    tmp_path: Path, *, development_mode: bool = False
) -> tuple[ProfileService, JsonProfileRepository]:
    paths = DataPaths(tmp_path / "data")
    repository = JsonProfileRepository(paths)
    logs = JsonLearningLogRepository(paths, repository)
    return (
        ProfileService(repository, logs, development_mode=development_mode),
        repository,
    )


def test_existing_profile_json_gets_default_preferences(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path / "data")
    paths.runtime_dir.mkdir(parents=True)
    paths.profiles_file.write_text(
        json.dumps(
            [
                {
                    "profile_id": "old-profile",
                    "display_name": "旧プロフィール",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ]
        ),
        encoding="utf-8",
    )

    profile = JsonProfileRepository(paths).get_profile("old-profile")

    assert profile.preferences.hint_provider is HintProviderId.OPENAI
    assert profile.preferences.last_problem_id is None
    assert not profile.is_development


def test_provider_preference_is_persisted_per_profile(tmp_path: Path) -> None:
    service, repository = make_profile_service(tmp_path)
    profile = service.create_profile("学習者")
    service.set_last_problem(profile.profile_id, "l0_two_values")

    service.set_hint_provider(profile.profile_id, HintProviderId.GEMINI)

    preferences = repository.get_profile(profile.profile_id).preferences
    assert preferences.hint_provider is HintProviderId.GEMINI
    assert preferences.last_problem_id == "l0_two_values"


def test_development_profile_is_persistent_and_hidden_in_production(
    tmp_path: Path,
) -> None:
    development, repository = make_profile_service(tmp_path, development_mode=True)

    first = development.default_profile()
    second = development.default_profile()

    assert first is not None
    assert second is not None
    assert first.profile_id == DEVELOPMENT_PROFILE_ID
    assert second.profile_id == DEVELOPMENT_PROFILE_ID

    paths = DataPaths(tmp_path / "data")
    production_logs = JsonLearningLogRepository(paths, repository)
    production = ProfileService(repository, production_logs, development_mode=False)
    assert all(not profile.is_development for profile in production.list_profiles())
