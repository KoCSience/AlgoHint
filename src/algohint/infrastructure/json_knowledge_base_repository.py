"""Validated filesystem adapter for reviewed problem knowledge."""

import json

from algohint.domain.models import ProblemKnowledge
from algohint.infrastructure.filesystem_paths import DataPaths


class JsonKnowledgeBaseRepository:
    """Load public research context without accessing hidden tests or solutions."""

    def __init__(self, paths: DataPaths) -> None:
        self._paths = paths

    def get_knowledge(self, problem_id: str) -> ProblemKnowledge:
        """Validate one problem-scoped knowledge document and its identity."""

        path = self._paths.problems_dir / problem_id / "knowledge.json"
        if not path.is_file():
            raise KeyError(f"Knowledge base is unavailable for {problem_id}")
        with path.open(encoding="utf-8") as file:
            knowledge = ProblemKnowledge.model_validate(json.load(file))
        if knowledge.problem_id != problem_id:
            raise ValueError("Knowledge base problem_id does not match its directory")
        return knowledge
