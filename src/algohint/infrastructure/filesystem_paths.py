"""Centralized paths prevent learner-generated data from leaking into content files."""

from pathlib import Path


class DataPaths:
    """Resolve the documented data layout from an explicit application data root."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir.resolve()

    @property
    def problems_dir(self) -> Path:
        return self.data_dir / "problems"

    @property
    def curriculum_file(self) -> Path:
        return self.data_dir / "curriculum.json"

    @property
    def runtime_dir(self) -> Path:
        return self.data_dir / "runtime"

    @property
    def profiles_file(self) -> Path:
        return self.runtime_dir / "profiles.json"

    @property
    def logs_dir(self) -> Path:
        return self.runtime_dir / "learning_logs"
