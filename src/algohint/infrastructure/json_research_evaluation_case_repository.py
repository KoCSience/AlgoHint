"""Validated adapter for the fixed Agentic Research evaluation dataset."""

import json

from pydantic import TypeAdapter

from algohint.domain.models import ResearchEvaluationCase
from algohint.infrastructure.filesystem_paths import DataPaths


class JsonResearchEvaluationCaseRepository:
    """Load exactly fifteen reviewed cases without external API calls."""

    def __init__(self, paths: DataPaths) -> None:
        self._path = paths.research_evaluation_file

    def list_cases(self) -> tuple[ResearchEvaluationCase, ...]:
        with self._path.open(encoding="utf-8") as file:
            cases = TypeAdapter(tuple[ResearchEvaluationCase, ...]).validate_python(
                json.load(file)
            )
        if len(cases) != 15:
            raise ValueError("research evaluation dataset must contain exactly 15 cases")
        case_ids = [case.case_id for case in cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("research evaluation case IDs must be unique")
        return cases
