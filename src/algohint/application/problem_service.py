"""Problem discovery and learner-safe content projection."""

from algohint.application.dto import LearnerProblemView
from algohint.domain.ports import ProblemRepository


class ProblemService:
    """Keep private judge assets out of problem views consumed by the UI."""

    def __init__(self, repository: ProblemRepository) -> None:
        self._repository = repository

    def list_problems(self):
        return self._repository.list_problems()

    def curriculum(self) -> list[dict[str, object]]:
        return self._repository.get_curriculum()

    def get_learner_problem(self, problem_id: str) -> LearnerProblemView:
        problem = self._repository.get_problem(problem_id)
        samples = self._repository.get_tests(problem_id, include_hidden=False)
        return LearnerProblemView(
            problem_id=problem.problem_id,
            title=problem.title,
            level=problem.level,
            tags=problem.tags,
            learning_goal=problem.learning_goal,
            statement=problem.statement,
            constraints=problem.constraints,
            input_format=problem.input_format,
            output_format=problem.output_format,
            samples=tuple((item.input_text, item.expected_output) for item in samples),
        )
