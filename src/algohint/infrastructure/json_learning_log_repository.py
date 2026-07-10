"""Atomic JSON persistence for local profiles and progress logs."""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from algohint.domain.models import LearningLog, Profile
from algohint.infrastructure.filesystem_paths import DataPaths


class JsonLearningLogRepository:
    """Persist only small aggregate learning records to a local data directory."""

    def __init__(self, paths: DataPaths) -> None:
        self._paths = paths
        self._paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._paths.logs_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_json_atomic(path: Path, payload: object) -> None:
        """Replace a file atomically so interruption does not corrupt progress."""

        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def list_profiles(self) -> list[Profile]:
        if not self._paths.profiles_file.exists():
            return []
        with self._paths.profiles_file.open(encoding="utf-8") as file:
            return TypeAdapter(list[Profile]).validate_python(json.load(file))

    def create_profile(self, display_name: str) -> Profile:
        cleaned_name = display_name.strip()
        existing = self.list_profiles()
        for profile in existing:
            if profile.display_name == cleaned_name:
                return profile
        profile = Profile(
            profile_id=str(uuid4()), display_name=cleaned_name, created_at=datetime.now(UTC)
        )
        self._write_json_atomic(
            self._paths.profiles_file,
            [item.model_dump(mode="json") for item in [*existing, profile]],
        )
        self.save_log(LearningLog(profile_id=profile.profile_id))
        return profile

    def _log_path(self, profile_id: str) -> Path:
        if not any(profile.profile_id == profile_id for profile in self.list_profiles()):
            raise KeyError("Unknown profile")
        return self._paths.logs_dir / f"{profile_id}.json"

    def load_log(self, profile_id: str) -> LearningLog:
        path = self._log_path(profile_id)
        if not path.exists():
            return LearningLog(profile_id=profile_id)
        with path.open(encoding="utf-8") as file:
            return LearningLog.model_validate(json.load(file))

    def save_log(self, log: LearningLog) -> None:
        self._write_json_atomic(
            self._paths.logs_dir / f"{log.profile_id}.json", log.model_dump(mode="json")
        )
