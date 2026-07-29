from pathlib import Path

import pytest

from algohint.application.profile_service import ProfileService
from algohint.application.tutor_service import (
    CloudConsentRequiredError,
    TutorService,
)
from algohint.domain.enums import (
    HintProviderId,
    HintTrigger,
    TutorRole,
)
from algohint.domain.models import (
    GeneratedHint,
    HintGenerationRequest,
    ProviderAvailability,
)
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_problem_repository import JsonProblemRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.json_tutor_session_repository import (
    JsonTutorSessionRepository,
)
from algohint.infrastructure.rule_based_hint_provider import RuleBasedHintProvider

DATA_DIR = Path(__file__).parents[1] / "data"


class FakeHintProvider:
    """Capture requests while returning deterministic provider output."""

    def __init__(
        self,
        text: str = "条件を小さな入力に置き換えて、変数の変化を追ってみましょう。",
        *,
        sends_data_off_device: bool = False,
        available: bool = True,
    ) -> None:
        self.text = text
        self.requests: list[HintGenerationRequest] = []
        self._availability = ProviderAvailability(
            available=available,
            sends_data_off_device=sends_data_off_device,
            reason=None if available else "not configured",
        )

    def availability(self) -> ProviderAvailability:
        return self._availability

    def generate(self, request: HintGenerationRequest) -> GeneratedHint:
        self.requests.append(request)
        return GeneratedHint(
            text=self.text,
            category=request.authored_hint.category,
            provider="fake",
            model_name="fake-v1",
        )


def make_tutor(
    tmp_path: Path, provider: FakeHintProvider
) -> tuple[TutorService, str, JsonTutorSessionRepository, JsonLearningLogRepository]:
    paths = DataPaths(tmp_path / "runtime-data")
    profiles = JsonProfileRepository(paths)
    logs = JsonLearningLogRepository(paths, profiles)
    profile = ProfileService(profiles, logs).create_profile("学習者")
    sessions = JsonTutorSessionRepository(paths)
    tutor = TutorService(
        JsonProblemRepository(DataPaths(DATA_DIR)),
        profiles,
        logs,
        sessions,
        {HintProviderId.OPENAI: provider},
        RuleBasedHintProvider(),
    )
    return tutor, profile.profile_id, sessions, logs


def test_question_and_hint_are_persisted_without_source_code(tmp_path: Path) -> None:
    provider = FakeHintProvider()
    tutor, profile_id, sessions, logs = make_tutor(tmp_path, provider)

    reply = tutor.request_hint(
        profile_id,
        "l0_two_values",
        trigger=HintTrigger.QUESTION,
        question="どの値を追えばよいですか？",
        source_code="print('do not persist this source')",
    )

    assert [message.role for message in reply.session.messages] == [
        TutorRole.USER,
        TutorRole.ASSISTANT,
    ]
    stored = sessions.load(profile_id, "l0_two_values")
    assert all("do not persist" not in message.text for message in stored.messages)
    assert provider.requests[0].source_code == "print('do not persist this source')"
    assert logs.load_log(profile_id).progress["l0_two_values"].hint_count == 1


def test_unsafe_provider_output_uses_rule_based_fallback(tmp_path: Path) -> None:
    provider = FakeHintProvider("```python\ndef solve():\n    return 1\n```")
    tutor, profile_id, _, _ = make_tutor(tmp_path, provider)

    reply = tutor.request_hint(
        profile_id,
        "l0_two_values",
        trigger=HintTrigger.STUCK,
    )

    assert reply.hint.used_fallback
    assert reply.hint.fallback_reason == "unsafe_output"
    assert "```" not in reply.hint.text


def test_off_device_provider_requires_session_consent(tmp_path: Path) -> None:
    provider = FakeHintProvider(sends_data_off_device=True)
    tutor, profile_id, sessions, _ = make_tutor(tmp_path, provider)

    with pytest.raises(CloudConsentRequiredError):
        tutor.request_hint(
            profile_id,
            "l0_two_values",
            trigger=HintTrigger.STUCK,
            cloud_consent=False,
        )

    assert not sessions.load(profile_id, "l0_two_values").messages
    assert not provider.requests


def test_history_is_bounded_and_can_be_cleared(tmp_path: Path) -> None:
    provider = FakeHintProvider()
    tutor, profile_id, sessions, _ = make_tutor(tmp_path, provider)

    for _ in range(21):
        tutor.request_hint(
            profile_id,
            "l0_two_values",
            trigger=HintTrigger.STUCK,
        )

    assert len(sessions.load(profile_id, "l0_two_values").messages) == 40
    tutor.clear_session(profile_id, "l0_two_values")
    assert not sessions.load(profile_id, "l0_two_values").messages


def test_oversized_source_is_not_sent_to_provider(tmp_path: Path) -> None:
    provider = FakeHintProvider()
    tutor, profile_id, _, _ = make_tutor(tmp_path, provider)

    reply = tutor.request_hint(
        profile_id,
        "l0_two_values",
        trigger=HintTrigger.STUCK,
        source_code="x" * 16_385,
    )

    assert reply.source_omitted
    assert provider.requests[0].source_code is None
