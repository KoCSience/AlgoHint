"""Atomic JSON persistence for local profiles and provider preferences."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import TypeAdapter

from algohint.domain.models import Profile, ProfilePreferences
from algohint.infrastructure.atomic_json import write_json_atomic
from algohint.infrastructure.filesystem_paths import DataPaths


class JsonProfileRepository:
    """Persist profile metadata without storing cloud consent or secrets."""

    def __init__(self, paths: DataPaths) -> None:
        self._paths = paths
        self._paths.runtime_dir.mkdir(parents=True, exist_ok=True)

    def list_profiles(self) -> list[Profile]:
        if not self._paths.profiles_file.exists():
            return []
        with self._paths.profiles_file.open(encoding="utf-8") as file:
            return TypeAdapter(list[Profile]).validate_python(json.load(file))

    def get_profile(self, profile_id: str) -> Profile:
        for profile in self.list_profiles():
            if profile.profile_id == profile_id:
                return profile
        raise KeyError("Unknown profile")

    def create_profile(self, display_name: str, preferences: ProfilePreferences) -> Profile:
        cleaned_name = display_name.strip()
        existing = self.list_profiles()
        for profile in existing:
            if profile.display_name == cleaned_name and not profile.is_development:
                return profile
        profile = Profile(
            profile_id=str(uuid4()),
            display_name=cleaned_name,
            created_at=datetime.now(UTC),
            preferences=preferences,
        )
        self.save_profile(profile)
        return profile

    def save_profile(self, profile: Profile) -> None:
        """Upsert one profile while preserving all unrelated local identities."""

        profiles = self.list_profiles()
        updated = [profile if item.profile_id == profile.profile_id else item for item in profiles]
        if not any(item.profile_id == profile.profile_id for item in profiles):
            updated.append(profile)
        write_json_atomic(
            self._paths.profiles_file,
            [item.model_dump(mode="json") for item in updated],
        )
