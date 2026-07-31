"""Application policy for consented, public-context grounded research."""

from __future__ import annotations

import uuid
from typing import Literal

from algohint.domain.models import (
    ResearchHistoryEntry,
    ResearchProviderRequest,
    ResearchResult,
    ResearchUsage,
)
from algohint.domain.enums import JudgeStatus
from algohint.domain.ports import (
    KnowledgeBaseRepository,
    LearningLogRepository,
    ProblemRepository,
    ProfileRepository,
    ResearchHistoryRepository,
    ResearchProvider,
)


class ResearchConsentRequiredError(ValueError):
    """Research must never run from an implicit UI or retry event."""


class GroundedResearchService:
    """Build public-only requests and persist final evidence per profile."""

    def __init__(
        self,
        problems: ProblemRepository,
        knowledge: KnowledgeBaseRepository,
        profiles: ProfileRepository,
        logs: LearningLogRepository,
        provider: ResearchProvider,
        history: ResearchHistoryRepository,
    ) -> None:
        self._problems = problems
        self._knowledge = knowledge
        self._profiles = profiles
        self._logs = logs
        self._provider = provider
        self._history = history

    def usage(self) -> ResearchUsage:
        """Read budget status without starting a search."""

        return self._provider.usage()

    def research(
        self,
        profile_id: str,
        problem_id: str,
        *,
        consent: bool,
    ) -> ResearchResult:
        """Send only reviewed public metadata after explicit per-action consent."""

        if not consent:
            raise ResearchConsentRequiredError(
                "Web検索の送信内容を確認し、専用の同意欄を選択してください。"
            )
        self._profiles.get_profile(profile_id)
        problem = self._problems.get_problem(problem_id)
        knowledge = self._knowledge.get_knowledge(problem_id)
        progress = self._logs.load_log(profile_id).progress.get(problem_id)
        judge_status: Literal[
            "WA", "RE", "TLE", "CE", "AC", "GIVE_UP", "UNKNOWN"
        ] = "UNKNOWN"
        hint_level = 1
        if progress is not None:
            hint_level = min(3, max(1, progress.hint_count + 1))
            if progress.gave_up:
                judge_status = "GIVE_UP"
            elif progress.solved:
                judge_status = "AC"
            elif progress.last_status is not None:
                if progress.last_status is JudgeStatus.WA:
                    judge_status = "WA"
                elif progress.last_status is JudgeStatus.RE:
                    judge_status = "RE"
                elif progress.last_status is JudgeStatus.TLE:
                    judge_status = "TLE"
                elif progress.last_status is JudgeStatus.CE:
                    judge_status = "CE"
                elif progress.last_status is JudgeStatus.AC:
                    judge_status = "AC"
        request = ResearchProviderRequest(
            problem_id=problem.problem_id,
            problem_title=problem.title,
            problem_summary=knowledge.public_summary,
            concepts=knowledge.concepts,
            search_terms=knowledge.search_terms,
            allowed_domains=tuple(dict.fromkeys(source.domain for source in knowledge.sources)),
            judge_status=judge_status,
            hint_level=hint_level,
            web_search_consent=True,
            client_request_id=uuid.uuid4().hex,
        )
        result = self._provider.research(request)
        self._history.save(
            profile_id,
            problem_id,
            judge_status,
            result,
        )
        return result

    def history(
        self,
        profile_id: str,
        problem_id: str,
        *,
        limit: int = 10,
    ) -> tuple[ResearchHistoryEntry, ...]:
        """Return only the selected profile's bounded research history."""

        return self._history.list(profile_id, problem_id, limit=limit)
