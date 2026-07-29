"""Atomic JSON persistence for profile-scoped aggregate progress logs."""

import json

from algohint.domain.models import LearningLog
from algohint.domain.ports import ProfileRepository
from algohint.infrastructure.atomic_json import write_json_atomic
from algohint.infrastructure.filesystem_paths import DataPaths


class JsonLearningLogRepository:
    """Persist only small aggregate learning records to a local data directory."""

    def __init__(self, paths: DataPaths, profiles: ProfileRepository) -> None:
        self._paths = paths
        self._profiles = profiles
        self._paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._paths.logs_dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self, profile_id: str):
        self._profiles.get_profile(profile_id)
        return self._paths.logs_dir / f"{profile_id}.json"

    def load_log(self, profile_id: str) -> LearningLog:
        path = self._log_path(profile_id)
        if not path.exists():
            return LearningLog(profile_id=profile_id)
        with path.open(encoding="utf-8") as file:
            return LearningLog.model_validate(json.load(file))

    def save_log(self, log: LearningLog) -> None:
        self._profiles.get_profile(log.profile_id)
        write_json_atomic(
            self._paths.logs_dir / f"{log.profile_id}.json", log.model_dump(mode="json")
        )
