from pathlib import Path

from algohint.application.problem_service import ProblemService
from algohint.domain.enums import QuizTopic
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_problem_repository import JsonProblemRepository


DATA_DIR = Path(__file__).parents[1] / "data"


def test_repository_loads_all_initial_problems() -> None:
    repository = JsonProblemRepository(DataPaths(DATA_DIR))

    assert len(repository.list_problems()) == 5
    assert len(repository.get_tests("l3_frequency_count", include_hidden=False)) == 2
    assert len(repository.get_tests("l3_frequency_count", include_hidden=True)) == 5
    for problem in repository.list_problems():
        review = repository.get_review_material(problem.problem_id)
        assert len(review.questions) == 5
        assert {question.topic for question in review.questions} == set(QuizTopic)


def test_learner_problem_view_excludes_private_assets() -> None:
    repository = JsonProblemRepository(DataPaths(DATA_DIR))
    view = ProblemService(repository).get_learner_problem("l0_two_values")

    assert view.problem_id == "l0_two_values"
    assert len(view.samples) == 2
    assert not hasattr(view, "hidden_tests")
    assert not hasattr(view, "model_solution")
