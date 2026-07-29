"""Contract tests for the private Transformers Gemma service client."""

import json
import logging

import httpx
import pytest

from algohint.domain.enums import (
    GemmaDeployment,
    HintCategory,
    HintTrigger,
    ProviderFailureReason,
)
from algohint.domain.errors import HintProviderError
from algohint.domain.models import Hint, HintGenerationRequest
from algohint.infrastructure.transformers_http_hint_provider import (
    TransformersHttpHintProvider,
)

API_KEY = "private-test-key-that-is-long-enough"
MODEL = "google/gemma-4-12B-it"


def make_request() -> HintGenerationRequest:
    return HintGenerationRequest(
        learner_key="b" * 64,
        problem_id="problem",
        title="二つの値",
        statement="二つの整数を処理する。",
        constraints="0以上",
        learning_goal="入力を確認する",
        tags=("input",),
        authored_hint=Hint(
            level=1,
            category=HintCategory.DEBUG,
            text="小さな入力で変数を追いましょう。",
        ),
        hint_count=0,
        trigger=HintTrigger.STUCK,
        source_code="print(0)",
    )


def provider_with_handler(
    handler,
    *,
    development_mode: bool = False,
) -> tuple[TransformersHttpHintProvider, list[httpx.Client]]:
    clients: list[httpx.Client] = []

    def factory() -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    return (
        TransformersHttpHintProvider(
            MODEL,
            "http://127.0.0.1:18000/v1",
            deployment=GemmaDeployment.REMOTE,
            client_factory=factory,
            development_mode=development_mode,
        ),
        clients,
    )


def test_generate_uses_minimal_contract_and_trusted_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"model": MODEL, "text": "境界値で変数の変化を確認しましょう。"},
        )

    provider, clients = provider_with_handler(handler)

    hint = provider.generate(make_request())

    assert provider.availability().available
    assert provider.availability().sends_data_off_device
    assert hint.provider == "gemma"
    assert hint.model_name == MODEL
    assert hint.category is HintCategory.DEBUG
    assert captured["authorization"] == f"Bearer {API_KEY}"
    body = captured["body"]
    assert isinstance(body, dict)
    assert set(body) == {"model", "system_instructions", "learner_context"}
    assert "print(0)" in str(body["learner_context"])
    assert all(client.is_closed for client in clients)


def test_doctor_uses_only_model_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": MODEL,
                        "revision": "pinned",
                        "backend": "transformers",
                        "ready": True,
                    }
                ]
            },
        )

    provider, clients = provider_with_handler(handler)

    diagnostic = provider.diagnose()

    assert diagnostic.healthy
    assert paths == ["/v1/models"]
    assert all(client.is_closed for client in clients)


@pytest.mark.parametrize(
    ("status_code", "reason", "retryable"),
    [
        (400, ProviderFailureReason.INVALID_REQUEST, False),
        (401, ProviderFailureReason.AUTHENTICATION_OR_PERMISSION, False),
        (403, ProviderFailureReason.AUTHENTICATION_OR_PERMISSION, False),
        (404, ProviderFailureReason.MODEL_NOT_FOUND, False),
        (413, ProviderFailureReason.INVALID_REQUEST, False),
        (422, ProviderFailureReason.INVALID_REQUEST, False),
        (429, ProviderFailureReason.RATE_OR_QUOTA_EXCEEDED, True),
        (502, ProviderFailureReason.PROVIDER_UNAVAILABLE, True),
        (503, ProviderFailureReason.PROVIDER_UNAVAILABLE, True),
        (504, ProviderFailureReason.TIMEOUT, True),
    ],
)
def test_classifies_http_failures(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    reason: ProviderFailureReason,
    retryable: bool,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"detail": "private raw server response"},
        )

    provider, _ = provider_with_handler(handler)

    with pytest.raises(HintProviderError) as raised:
        provider.generate(make_request())

    assert raised.value.reason_code is reason
    assert raised.value.http_status == status_code
    assert raised.value.retryable is retryable
    assert "private raw server response" not in str(raised.value)


def test_invalid_response_is_classified_without_exposing_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)
    provider, _ = provider_with_handler(
        lambda request: httpx.Response(200, text="private-invalid-response")
    )

    with pytest.raises(HintProviderError) as raised:
        provider.generate(make_request())

    assert raised.value.reason_code is ProviderFailureReason.INVALID_STRUCTURED_RESPONSE
    assert "private-invalid-response" not in str(raised.value)


def test_development_traceback_redacts_key_and_omits_prompt(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_prompt = "print(0)"
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)
    provider, _ = provider_with_handler(
        lambda request: (_ for _ in ()).throw(
            httpx.ConnectError(f"Authorization: Bearer {API_KEY}", request=request)
        ),
        development_mode=True,
    )

    with caplog.at_level(
        logging.ERROR,
        logger="algohint.infrastructure.transformers_http_hint_provider",
    ):
        with pytest.raises(HintProviderError):
            provider.generate(make_request())

    assert "gemma_provider_exception" in caplog.text
    assert "[REDACTED]" in caplog.text
    assert API_KEY not in caplog.text
    assert private_prompt not in caplog.text


def test_missing_key_is_unavailable_even_with_tunnel_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALGOHINT_GEMMA_API_KEY", raising=False)
    provider, _ = provider_with_handler(lambda request: pytest.fail("must not connect"))

    availability = provider.availability()
    diagnostic = provider.diagnose()

    assert not availability.available
    assert availability.sends_data_off_device
    assert diagnostic.reason_code is ProviderFailureReason.NOT_CONFIGURED
