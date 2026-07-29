import json
from types import SimpleNamespace

import pytest
from google.genai.errors import ClientError, ServerError

from algohint.domain.enums import (
    HintCategory,
    HintProviderId,
    HintTrigger,
    JudgeStatus,
    ProviderFailureReason,
)
from algohint.domain.errors import HintProviderError
from algohint.domain.models import Hint, HintGenerationRequest
from algohint.infrastructure.gemma_hint_provider import GemmaHintProvider
from algohint.infrastructure.gemini_hint_provider import GeminiHintProvider
from algohint.infrastructure.hint_prompt import build_hint_prompt
from algohint.infrastructure.openai_hint_provider import OpenAIHintProvider


def make_request() -> HintGenerationRequest:
    return HintGenerationRequest(
        learner_key="a" * 64,
        problem_id="problem",
        title="二つの値",
        statement="二つの整数を処理する。",
        constraints="0以上",
        learning_goal="入力を確認する",
        tags=("input",),
        authored_hint=Hint(
            level=1,
            category=HintCategory.UNDERSTANDING,
            text="入力と出力を言葉で整理しましょう。",
        ),
        hint_count=0,
        trigger=HintTrigger.JUDGE_RESULT,
        question="どこを確認しますか？",
        source_code="print(0)",
        judge_status=JudgeStatus.WA,
        diagnostic_summary="出力が一致しません",
    )


class FakeOpenAIResponses:
    def __init__(self, text: str) -> None:
        self.text = text
        self.kwargs: dict[str, object] = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text=self.text)


class FakeGemmaCompletions:
    def __init__(self, text: str) -> None:
        self.text = text
        self.kwargs: dict[str, object] = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        message = SimpleNamespace(content=self.text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeGeminiModels:
    def __init__(self, text: str) -> None:
        self.text = text
        self.kwargs: dict[str, object] = {}

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(text=self.text)


class FailingGeminiModels:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate_content(self, **kwargs):
        raise self.error

    def get(self, **kwargs):
        raise self.error


class BlockedGeminiResponse:
    @property
    def text(self) -> str:
        raise ValueError("raw blocked response must remain private")


def response_json(text: str = "最小ケースで変数の変化を追いましょう。") -> str:
    return json.dumps({"text": text, "category": "understanding"}, ensure_ascii=False)


def test_openai_provider_uses_responses_without_tools_or_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    responses = FakeOpenAIResponses(response_json())
    client = SimpleNamespace(responses=responses)
    provider = OpenAIHintProvider("gpt-5.6-sol", client_factory=lambda: client)

    hint = provider.generate(make_request())

    assert provider.availability().sends_data_off_device
    assert hint.provider == "openai"
    assert responses.kwargs["store"] is False
    assert responses.kwargs["safety_identifier"] == "a" * 64
    assert "tools" not in responses.kwargs


def test_gemma_provider_uses_configured_openai_compatible_endpoint() -> None:
    completions = FakeGemmaCompletions(response_json())
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = GemmaHintProvider(
        "google/gemma-4-12B-it",
        "http://127.0.0.1:8000/v1",
        client_factory=lambda: client,
    )

    hint = provider.generate(make_request())

    assert provider.availability().available
    assert not provider.availability().sends_data_off_device
    assert hint.provider == "gemma"
    assert completions.kwargs["model"] == "google/gemma-4-12B-it"


def test_remote_gemma_endpoint_requires_off_device_consent() -> None:
    """A future remote vLLM host must not inherit the local-server trust level."""

    availability = GemmaHintProvider(
        "google/gemma-4-12B-it", "https://gemma.example.test/v1"
    ).availability()

    assert availability.available
    assert availability.sends_data_off_device


def test_gemini_provider_requests_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-placeholder")
    models = FakeGeminiModels(response_json())
    provider = GeminiHintProvider(
        "gemini-3.6-flash",
        client_factory=lambda: SimpleNamespace(models=models),
    )

    hint = provider.generate(make_request())

    assert provider.availability().sends_data_off_device
    assert hint.provider == "gemini"
    config = models.kwargs["config"]
    assert isinstance(config, dict)
    assert config["response_mime_type"] == "application/json"


def test_gemini_provider_pins_developer_api_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambient Vertex settings must not replace the configured API-key flow."""

    from google import genai

    monkeypatch.setenv("GEMINI_API_KEY", "  test-only-placeholder  ")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "true")
    captured: dict[str, object] = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(genai, "Client", fake_client)

    GeminiHintProvider("gemini-3.6-flash")._client()

    assert captured["api_key"] == "test-only-placeholder"
    assert captured["vertexai"] is False
    assert captured["enterprise"] is False


@pytest.mark.parametrize(
    ("status", "reason", "retryable"),
    [
        (400, ProviderFailureReason.INVALID_REQUEST, False),
        (401, ProviderFailureReason.AUTHENTICATION_OR_PERMISSION, False),
        (403, ProviderFailureReason.AUTHENTICATION_OR_PERMISSION, False),
        (404, ProviderFailureReason.MODEL_NOT_FOUND, False),
        (408, ProviderFailureReason.TIMEOUT, True),
        (499, ProviderFailureReason.TIMEOUT, True),
        (429, ProviderFailureReason.RATE_OR_QUOTA_EXCEEDED, True),
        (500, ProviderFailureReason.PROVIDER_UNAVAILABLE, True),
        (503, ProviderFailureReason.PROVIDER_UNAVAILABLE, True),
        (504, ProviderFailureReason.TIMEOUT, True),
    ],
)
def test_gemini_provider_classifies_api_errors(
    status: int,
    reason: ProviderFailureReason,
    retryable: bool,
) -> None:
    error_class = ServerError if status >= 500 else ClientError
    api_error = error_class(
        status,
        {
            "error": {
                "code": status,
                "status": "TEST_STATUS",
                "message": "raw provider response must remain private",
            }
        },
    )
    provider = GeminiHintProvider(
        "gemini-3.6-flash",
        client_factory=lambda: SimpleNamespace(models=FailingGeminiModels(api_error)),
    )

    with pytest.raises(HintProviderError) as raised:
        provider.generate(make_request())

    assert raised.value.reason_code is reason
    assert raised.value.http_status == status
    assert raised.value.retryable is retryable
    assert "raw provider response" not in str(raised.value)


def test_gemini_provider_classifies_transport_timeout() -> None:
    provider = GeminiHintProvider(
        "gemini-3.6-flash",
        client_factory=lambda: SimpleNamespace(
            models=FailingGeminiModels(TimeoutError("private network detail"))
        ),
    )

    with pytest.raises(HintProviderError) as raised:
        provider.generate(make_request())

    assert raised.value.reason_code is ProviderFailureReason.TIMEOUT
    assert raised.value.retryable
    assert "private network detail" not in str(raised.value)


@pytest.mark.parametrize(
    ("message", "reason", "retryable"),
    [
        (
            "Could not resolve API token from the environment",
            ProviderFailureReason.AUTHENTICATION_OR_PERMISSION,
            False,
        ),
        (
            "Operation operations/123 timed out.\nprivate operation state",
            ProviderFailureReason.TIMEOUT,
            True,
        ),
        (
            "unexpected SDK runtime failure",
            ProviderFailureReason.UNKNOWN_PROVIDER_ERROR,
            False,
        ),
    ],
)
def test_gemini_provider_classifies_runtime_errors(
    message: str,
    reason: ProviderFailureReason,
    retryable: bool,
) -> None:
    provider = GeminiHintProvider(
        "gemini-3.6-flash",
        client_factory=lambda: SimpleNamespace(models=FailingGeminiModels(RuntimeError(message))),
    )

    with pytest.raises(HintProviderError) as raised:
        provider.generate(make_request())

    assert raised.value.reason_code is reason
    assert raised.value.retryable is retryable
    assert message not in str(raised.value)


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (SimpleNamespace(text=""), ProviderFailureReason.EMPTY_OR_BLOCKED_RESPONSE),
        (BlockedGeminiResponse(), ProviderFailureReason.EMPTY_OR_BLOCKED_RESPONSE),
        (SimpleNamespace(text="not-json"), ProviderFailureReason.INVALID_STRUCTURED_RESPONSE),
        (
            SimpleNamespace(text='{"text":"ヒント","category":"unknown"}'),
            ProviderFailureReason.INVALID_STRUCTURED_RESPONSE,
        ),
    ],
)
def test_gemini_provider_classifies_invalid_responses(
    response: object, reason: ProviderFailureReason
) -> None:
    models = SimpleNamespace(generate_content=lambda **kwargs: response)
    provider = GeminiHintProvider(
        "gemini-3.6-flash",
        client_factory=lambda: SimpleNamespace(models=models),
    )

    with pytest.raises(HintProviderError) as raised:
        provider.generate(make_request())

    assert raised.value.reason_code is reason


def test_invalid_provider_response_is_a_recoverable_error() -> None:
    responses = FakeOpenAIResponses("not json")
    provider = OpenAIHintProvider(
        "gpt-5.6-sol",
        client_factory=lambda: SimpleNamespace(responses=responses),
    )

    with pytest.raises(HintProviderError):
        provider.generate(make_request())


def test_prompt_contains_only_explicit_safe_context() -> None:
    prompt = build_hint_prompt(make_request())

    assert "print(0)" in prompt
    assert "どこを確認" in prompt
    assert "model_solution" not in prompt
    assert "hidden_tests" not in prompt
    assert "OPENAI_API_KEY" not in prompt


def test_unconfigured_providers_report_safe_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert not OpenAIHintProvider("gpt-5.6-sol").availability().available
    assert not GeminiHintProvider("gemini-3.6-flash").availability().available
    assert not GemmaHintProvider("gemma", "").availability().available
    assert not GemmaHintProvider("gemma", "not-a-url").availability().available
    assert HintProviderId.OPENAI.value == "openai"


def test_gemini_provider_rejects_whitespace_only_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", " \t ")

    assert not GeminiHintProvider("gemini-3.6-flash").availability().available
