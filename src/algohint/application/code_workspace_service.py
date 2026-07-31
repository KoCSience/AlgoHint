"""Profile/problem code workspace operations independent from the Gradio adapter."""

from algohint.domain.models import (
    CodeDraft,
    CodeSnapshot,
    CodeSnapshotSummary,
)
from algohint.domain.ports import CodeHistoryRepository

MAX_SOURCE_BYTES = 1_048_576
DEFAULT_HISTORY_PAGE_SIZE = 20


class CodeWorkspaceService:
    """Validate source size and expose drafts/history without judging code."""

    def __init__(self, history: CodeHistoryRepository) -> None:
        self._history = history

    @staticmethod
    def validate_source(source: str) -> None:
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("コードはUTF-8で1 MiB以内にしてください。")

    def load_draft(self, profile_id: str, problem_id: str) -> CodeDraft:
        return self._history.load_draft(profile_id, problem_id)

    def save_draft(
        self,
        profile_id: str,
        problem_id: str,
        source: str,
        *,
        expected_revision: int,
    ) -> CodeDraft:
        self.validate_source(source)
        return self._history.save_draft(
            profile_id,
            problem_id,
            source,
            expected_revision=expected_revision,
        )

    def history(
        self,
        profile_id: str,
        problem_id: str,
        *,
        page: int = 0,
    ) -> tuple[tuple[CodeSnapshotSummary, ...], int]:
        if page < 0:
            raise ValueError("page must not be negative")
        total = self._history.count_snapshots(profile_id, problem_id)
        entries = self._history.list_snapshots(
            profile_id,
            problem_id,
            limit=DEFAULT_HISTORY_PAGE_SIZE,
            offset=page * DEFAULT_HISTORY_PAGE_SIZE,
        )
        return entries, total

    def get_snapshot(
        self,
        profile_id: str,
        problem_id: str,
        snapshot_id: str,
    ) -> CodeSnapshot:
        return self._history.get_snapshot(profile_id, problem_id, snapshot_id)

    def delete_snapshot(
        self,
        profile_id: str,
        problem_id: str,
        snapshot_id: str,
    ) -> bool:
        return self._history.delete_snapshot(profile_id, problem_id, snapshot_id)
