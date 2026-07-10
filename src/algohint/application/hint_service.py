"""Staged hint use case with a conservative answer-leak guard."""

import re

from algohint.domain.models import Hint, ProblemProgress
from algohint.domain.ports import LearningLogRepository, ProblemRepository
from algohint.infrastructure.rule_based_hint_client import RuleBasedHintClient


class HintService:
    """Advance one hint at a time and fall back if authored content is unsafe."""

    _leak_patterns = (
        re.compile(r"```", re.IGNORECASE),
        re.compile(r"def\s+solve", re.IGNORECASE),
        re.compile(r"答えは"),
        re.compile(r"正解は"),
    )
    _fallback = "問題文と制約を自分の言葉で整理し、最小の入力を手計算して確認してみましょう。"

    def __init__(
        self,
        problems: ProblemRepository,
        logs: LearningLogRepository,
        client: RuleBasedHintClient | None = None,
    ) -> None:
        self._problems = problems
        self._logs = logs
        self._client = client or RuleBasedHintClient()

    @classmethod
    def _is_safe(cls, text: str) -> bool:
        return not any(pattern.search(text) for pattern in cls._leak_patterns)

    def request(self, profile_id: str, problem_id: str) -> Hint:
        log = self._logs.load_log(profile_id)
        progress = log.progress.get(problem_id, ProblemProgress())
        problem = self._problems.get_problem(problem_id)
        hint = self._client.generate(problem, progress.hint_count, progress.last_status)
        if not self._is_safe(hint.text):
            hint = hint.model_copy(update={"text": self._fallback, "leak_checked": False})
        else:
            hint = hint.model_copy(update={"leak_checked": True})
        updated = progress.model_copy(update={"hint_count": progress.hint_count + 1})
        self._logs.save_log(log.model_copy(update={"progress": {**log.progress, problem_id: updated}}))
        return hint
