"""Small UI composition object that avoids a service locator in callbacks."""

from dataclasses import dataclass

from algohint.application.completion_review_service import CompletionReviewService
from algohint.application.completion_service import CompletionService
from algohint.application.exercise_selection_service import ExerciseSelectionService
from algohint.application.learning_report_service import LearningReportService
from algohint.application.problem_service import ProblemService
from algohint.application.profile_service import ProfileService
from algohint.application.research_service import GroundedResearchService
from algohint.application.submission_service import SubmissionService
from algohint.application.tutor_service import TutorService
from algohint.domain.ports import ProblemRepository


@dataclass(frozen=True)
class ApplicationServices:
    """Explicit dependencies supplied to the UI composition root."""

    profiles: ProfileService
    selections: ExerciseSelectionService
    reviews: CompletionReviewService
    problems: ProblemService
    submissions: SubmissionService
    tutor: TutorService
    completions: CompletionService
    reports: LearningReportService
    teacher_repository: ProblemRepository
    research: GroundedResearchService | None = None
