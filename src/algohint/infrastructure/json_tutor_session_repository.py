"""Thread-safe local persistence for bounded tutoring conversations."""

import json
from pathlib import Path
from threading import RLock

from algohint.domain.models import TutorMessage, TutorSession
from algohint.infrastructure.atomic_json import write_json_atomic
from algohint.infrastructure.filesystem_paths import DataPaths


class JsonTutorSessionRepository:
    """Persist questions and hints without retaining learner source or diagnostics."""

    def __init__(self, paths: DataPaths) -> None:
        self._paths = paths
        self._lock = RLock()
        self._paths.tutor_sessions_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, profile_id: str, problem_id: str) -> Path:
        # Validation prevents identifiers from escaping the runtime directory.
        empty = TutorSession(profile_id=profile_id, problem_id=problem_id)
        return self._paths.tutor_sessions_dir / empty.profile_id / f"{empty.problem_id}.json"

    def load(self, profile_id: str, problem_id: str) -> TutorSession:
        path = self._path(profile_id, problem_id)
        with self._lock:
            if not path.exists():
                return TutorSession(profile_id=profile_id, problem_id=problem_id)
            with path.open(encoding="utf-8") as file:
                return TutorSession.model_validate(json.load(file))

    def save(self, session: TutorSession) -> None:
        with self._lock:
            write_json_atomic(
                self._path(session.profile_id, session.problem_id),
                session.model_dump(mode="json"),
            )

    def append(
        self,
        profile_id: str,
        problem_id: str,
        messages: tuple[TutorMessage, ...],
        *,
        limit: int,
    ) -> TutorSession:
        """Append under one lock so concurrent browser callbacks cannot lose turns."""

        with self._lock:
            current = self.load(profile_id, problem_id)
            updated = current.model_copy(
                update={"messages": (*current.messages, *messages)[-limit:]}
            )
            self.save(updated)
            return updated

    def clear(self, profile_id: str, problem_id: str) -> None:
        """Overwrite one conversation with an empty session, preserving aggregates."""

        with self._lock:
            empty = TutorSession(profile_id=profile_id, problem_id=problem_id)
            write_json_atomic(self._path(profile_id, problem_id), empty.model_dump(mode="json"))
