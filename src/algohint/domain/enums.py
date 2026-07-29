"""Closed vocabularies used to prevent ambiguous learning and judge states."""

from enum import StrEnum


class JudgeStatus(StrEnum):
    """The outcome of a code submission as determined by LocalJudge."""

    AC = "AC"
    WA = "WA"
    RE = "RE"
    TLE = "TLE"
    CE = "CE"
    IE = "IE"


class TestVisibility(StrEnum):
    """Whether a testcase may be revealed in the learner interface."""

    SAMPLE = "sample"
    HIDDEN = "hidden"


class HintCategory(StrEnum):
    """The learning purpose of each progressively disclosed hint."""

    UNDERSTANDING = "understanding"
    COMPLEXITY = "complexity"
    APPROACH = "approach"
    IMPLEMENTATION = "implementation"
    DEBUG = "debug"


class CompareMode(StrEnum):
    """Supported output comparisons; MVP intentionally exposes only trim."""

    TRIM = "trim"


class SubmissionMode(StrEnum):
    """Select public samples or the complete learner-safe judge flow."""

    SAMPLE = "sample"
    FULL = "full"


class HintProviderId(StrEnum):
    """Learner-selectable adaptive hint providers."""

    OPENAI = "openai"
    GEMMA = "gemma"
    GEMINI = "gemini"
