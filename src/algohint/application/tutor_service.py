"""Adaptive tutoring orchestration with consent and deterministic fallback."""

import hashlib
import logging
from datetime import UTC, datetime
from typing import Mapping

from algohint.application.dto import LearnerDiagnostic, TutorReply
from algohint.application.hint_safety_policy import HintSafetyPolicy
from algohint.domain.enums import (
    HintCategory,
    HintProviderId,
    HintTrigger,
    ProviderFailureReason,
    TutorRole,
)
from algohint.domain.errors import HintProviderError
from algohint.domain.models import (
    GeneratedHint,
    HintGenerationRequest,
    ProblemProgress,
    ProviderAvailability,
    TutorMessage,
)
from algohint.domain.ports import (
    HintProvider,
    LearningLogRepository,
    ProblemRepository,
    ProfileRepository,
    TutorSessionRepository,
)

LOGGER = logging.getLogger(__name__)
MAX_SOURCE_CHARS = 16_384
MAX_MESSAGES = 40


class CloudConsentRequiredError(PermissionError):
    """Raised before any off-device provider receives learner content."""


class TutorService:
    """Build safe provider requests and persist only questions and displayed hints."""

    def __init__(
        self,
        problems: ProblemRepository,
        profiles: ProfileRepository,
        logs: LearningLogRepository,
        sessions: TutorSessionRepository,
        providers: Mapping[HintProviderId, HintProvider],
        fallback: HintProvider,
        safety: HintSafetyPolicy | None = None,
    ) -> None:
        self._problems = problems
        self._profiles = profiles
        self._logs = logs
        self._sessions = sessions
        self._providers = providers
        self._fallback = fallback
        self._safety = safety or HintSafetyPolicy()

    def request_hint(
        self,
        profile_id: str,
        problem_id: str,
        *,
        trigger: HintTrigger,
        source_code: str = "",
        question: str | None = None,
        diagnostic: LearnerDiagnostic | None = None,
        cloud_consent: bool = False,
    ) -> TutorReply:
        """Generate one hint without persisting source code or raw diagnostics."""

        cleaned_question = self._validated_question(trigger, question)
        profile = self._profiles.get_profile(profile_id)
        selected = self._providers.get(profile.preferences.hint_provider)
        selected_availability = selected.availability() if selected else None
        if (
            selected_availability is not None
            and selected_availability.sends_data_off_device
            and not cloud_consent
        ):
            # Consent remains session-scoped; a stored provider preference is not permission.
            raise CloudConsentRequiredError("クラウド送信への同意が必要です。")

        log = self._logs.load_log(profile_id)
        progress = log.progress.get(problem_id, ProblemProgress())
        problem = self._problems.get_problem(problem_id)
        session = self._sessions.load(profile_id, problem_id)
        source_omitted = len(source_code) > MAX_SOURCE_CHARS
        authored = problem.hints[min(progress.hint_count, len(problem.hints) - 1)]
        request = HintGenerationRequest(
            learner_key=hashlib.sha256(profile_id.encode("utf-8")).hexdigest(),
            problem_id=problem.problem_id,
            title=problem.title,
            statement=problem.statement,
            constraints=problem.constraints,
            learning_goal=problem.learning_goal,
            tags=problem.tags,
            authored_hint=authored,
            hint_count=progress.hint_count,
            trigger=trigger,
            question=cleaned_question,
            source_code=None if source_omitted else source_code or None,
            judge_status=progress.last_status,
            diagnostic_summary=diagnostic.summary if diagnostic else None,
            diagnostic_details=diagnostic.details if diagnostic else None,
            released_explanation=problem.explanation
            if progress.solved or progress.gave_up
            else None,
            history=session.messages,
        )
        hint = self._generate(selected, selected_availability, request)
        user_message = TutorMessage(
            role=TutorRole.USER,
            text=cleaned_question or self._trigger_text(trigger),
            created_at=datetime.now(UTC),
            trigger=trigger,
        )
        assistant_message = TutorMessage(
            role=TutorRole.ASSISTANT,
            text=hint.text,
            created_at=datetime.now(UTC),
            provider=hint.provider,
            model_name=hint.model_name,
        )
        updated_session = self._sessions.append(
            profile_id,
            problem_id,
            (user_message, assistant_message),
            limit=MAX_MESSAGES,
        )
        updated_progress = progress.model_copy(update={"hint_count": progress.hint_count + 1})
        self._logs.save_log(
            log.model_copy(update={"progress": {**log.progress, problem_id: updated_progress}})
        )
        return TutorReply(hint=hint, session=updated_session, source_omitted=source_omitted)

    def load_session(self, profile_id: str, problem_id: str):
        """Load a conversation for profile/problem changes in the UI."""

        self._profiles.get_profile(profile_id)
        self._problems.get_problem(problem_id)
        return self._sessions.load(profile_id, problem_id)

    def clear_session(self, profile_id: str, problem_id: str) -> None:
        """Clear free-form tutoring text without changing aggregate progress."""

        self._profiles.get_profile(profile_id)
        self._problems.get_problem(problem_id)
        self._sessions.clear(profile_id, problem_id)

    def provider_availability(self, provider_id: HintProviderId) -> ProviderAvailability:
        """Expose only safe readiness metadata for the settings UI."""

        provider = self._providers.get(provider_id)
        if provider is None:
            return ProviderAvailability(available=False, reason="プロバイダが登録されていません。")
        return provider.availability()

    def _generate(
        self,
        selected: HintProvider | None,
        availability: ProviderAvailability | None,
        request: HintGenerationRequest,
    ) -> GeneratedHint:
        fallback_reason: str | None = None
        failure: HintProviderError | None = None
        if selected is None or availability is None or not availability.available:
            fallback_reason = "provider_unavailable"
        else:
            try:
                generated = selected.generate(request)
            except HintProviderError as error:
                failure = error
                fallback_reason = error.reason_code.value
            except ValueError as error:
                failure = HintProviderError(
                    reason_code=ProviderFailureReason.UNKNOWN_PROVIDER_ERROR,
                    provider=selected.__class__.__name__,
                    model="unknown",
                    exception_type=error.__class__.__name__,
                )
                fallback_reason = failure.reason_code.value
            else:
                if self._safety.is_safe(generated.text):
                    return generated
                fallback_reason = "unsafe_output"
        if failure is not None:
            LOGGER.warning(
                (
                    "hint_provider_fallback provider=%s model=%s reason_code=%s "
                    "http_status=%s retryable=%s exception_type=%s"
                ),
                failure.provider,
                failure.model,
                failure.reason_code.value,
                failure.http_status,
                failure.retryable,
                failure.exception_type,
            )
        else:
            LOGGER.warning(
                "hint_provider_fallback provider=%s model=%s reason_code=%s",
                selected.__class__.__name__ if selected is not None else "missing",
                generated.model_name if fallback_reason == "unsafe_output" else "unknown",
                fallback_reason,
            )
        fallback = self._fallback.generate(request)
        if not self._safety.is_safe(fallback.text):
            fallback = GeneratedHint(
                text="問題文と制約を自分の言葉で整理し、最小の入力を手計算してみましょう。",
                category=HintCategory.UNDERSTANDING,
                provider="rule_based",
                model_name="safe-default-v1",
            )
        return fallback.model_copy(
            update={"used_fallback": True, "fallback_reason": fallback_reason}
        )

    @staticmethod
    def _validated_question(trigger: HintTrigger, question: str | None) -> str | None:
        cleaned = question.strip() if question else None
        if trigger is HintTrigger.QUESTION and not cleaned:
            raise ValueError("質問を入力してください。")
        if cleaned is not None and len(cleaned) > 1_000:
            raise ValueError("質問は1,000文字以内で入力してください。")
        return cleaned

    @staticmethod
    def _trigger_text(trigger: HintTrigger) -> str:
        return {
            HintTrigger.STUCK: "わからない",
            HintTrigger.JUDGE_RESULT: "この実行結果についてヒントがほしい",
            HintTrigger.QUESTION: "質問",
        }[trigger]
