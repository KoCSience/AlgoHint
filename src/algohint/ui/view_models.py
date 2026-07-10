"""Small UI composition object that avoids a service locator in callbacks."""

from dataclasses import dataclass

from algohint.application.explanation_service import ExplanationService
from algohint.application.hint_service import HintService
from algohint.application.learning_report_service import LearningReportService
from algohint.application.problem_service import ProblemService
from algohint.application.profile_service import ProfileService
from algohint.application.submission_service import SubmissionService
from algohint.domain.ports import ProblemRepository


@dataclass(frozen=True)
class ApplicationServices:
    """Explicit dependencies supplied to the UI composition root."""

    profiles: ProfileService
    problems: ProblemService
    submissions: SubmissionService
    hints: HintService
    explanations: ExplanationService
    reports: LearningReportService
    teacher_repository: ProblemRepository
