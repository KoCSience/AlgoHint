"""JSON-backed repository for self-authored exercises."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from algohint.domain.enums import TestVisibility
from algohint.domain.models import Problem, ReviewMaterial, TestCase
from algohint.infrastructure.filesystem_paths import DataPaths


class JsonProblemRepository:
    """Load content from the repository data directory with strict validation.

    Keeping hidden tests in a separate file makes accidental UI serialization less
    likely. It is an application boundary, not cryptographic protection.
    """

    def __init__(self, paths: DataPaths) -> None:
        self._paths = paths

    def _problem_dir(self, problem_id: str) -> Path:
        path = (self._paths.problems_dir / problem_id).resolve()
        if path.parent != self._paths.problems_dir.resolve():
            raise KeyError(f"Unknown problem: {problem_id}")
        return path

    @staticmethod
    def _read_json(path: Path) -> object:
        with path.open(encoding="utf-8") as file:
            return json.load(file)

    def list_problems(self) -> list[Problem]:
        return [
            self.get_problem(path.name)
            for path in sorted(self._paths.problems_dir.iterdir())
            if path.is_dir()
        ]

    def get_problem(self, problem_id: str) -> Problem:
        path = self._problem_dir(problem_id) / "problem.json"
        if not path.is_file():
            raise KeyError(f"Unknown problem: {problem_id}")
        return Problem.model_validate(self._read_json(path))

    def get_tests(self, problem_id: str, include_hidden: bool) -> list[TestCase]:
        directory = self._problem_dir(problem_id)
        samples = TypeAdapter(list[TestCase]).validate_python(
            self._read_json(directory / "samples.json")
        )
        if any(case.visibility is not TestVisibility.SAMPLE for case in samples):
            raise ValueError(f"Sample file has non-sample case: {problem_id}")
        if not include_hidden:
            return samples
        hidden = TypeAdapter(list[TestCase]).validate_python(
            self._read_json(directory / "hidden_tests.json")
        )
        if any(case.visibility is not TestVisibility.HIDDEN for case in hidden):
            raise ValueError(f"Hidden file has non-hidden case: {problem_id}")
        return [*samples, *hidden]

    def get_model_solution(self, problem_id: str) -> str:
        path = self._problem_dir(problem_id) / "model_solution.py"
        if not path.is_file():
            raise KeyError(f"No model solution: {problem_id}")
        return path.read_text(encoding="utf-8")

    def get_curriculum(self) -> list[dict[str, object]]:
        payload = self._read_json(self._paths.curriculum_file)
        if not isinstance(payload, list):
            raise ValueError("curriculum.json must be a list")
        return [dict(item) for item in payload if isinstance(item, dict)]

    def get_review_material(self, problem_id: str) -> ReviewMaterial:
        """Load answer-bearing review content only through the server repository."""

        path = self._problem_dir(problem_id) / "review.json"
        if not path.is_file():
            raise KeyError(f"No review material: {problem_id}")
        return ReviewMaterial.model_validate(self._read_json(path))
