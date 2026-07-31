"""Deterministic answer-leak checks applied after every generated hint."""

import re


class HintSafetyPolicy:
    """Reject output that is directly submit-ready or presents a final answer."""

    _blocked_patterns = (
        re.compile(r"```"),
        re.compile(r"\bdef\s+solve\s*\(", re.IGNORECASE),
        re.compile(r"^\s*(?:from|import)\s+\S+", re.IGNORECASE | re.MULTILINE),
        re.compile(r"(?:答え|正解)\s*は"),
        re.compile(r"そのまま(?:提出|コピー)"),
    )

    def is_safe(self, text: str) -> bool:
        """Return true only for bounded natural-language coaching."""

        return bool(text.strip()) and not any(
            pattern.search(text) for pattern in self._blocked_patterns
        )
