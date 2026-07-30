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

    @property
    def tutor_sessions_dir(self) -> Path:
        """Keep free-form tutoring text separate from aggregate progress."""

        return self.runtime_dir / "tutor_sessions"

    @property
    def review_history_dir(self) -> Path:
        """Use one bounded SQLite database per profile for detailed review history."""

        return self.runtime_dir / "review_history"

    @property
    def research_history_dir(self) -> Path:
        """Keep grounded-search history private and separate from authored content."""

        return self.runtime_dir / "research_history"

    @property
    def research_evaluation_file(self) -> Path:
        """Return the versioned fixed-case dataset used by offline evaluation."""

        return self.data_dir / "evaluation" / "research-cases.json"
