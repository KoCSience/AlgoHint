"""Contract tests for the private Transformers Gemma service client."""

import json
import logging

import httpx
import pytest

from algohint.domain.enums import (
    CodeReviewCategory,
    CompletionReason,
    GemmaDeployment,
    GemmaGenerationFailureCode,
    HintCategory,
    HintTrigger,
    PersonalizedQuizMode,
    ProviderFailureReason,
)
from algohint.domain.errors import HintProviderError
from algohint.domain.models import (
    CodeReviewRequest,
    Hint,
    HintGenerationRequest,
    PersonalizedQuizRequest,
)
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


def make_review_request() -> CodeReviewRequest:
    return CodeReviewRequest(
        learner_key="b" * 64,
        problem_id="problem",
        title="二つの値",
        statement="二つの整数を処理する。",
        constraints="0以上",
        learning_goal="入力を確認する",
        tags=("input",),
        released_explanation="二値を加算します。",
        source_code="print(0)",
        completion_reason=CompletionReason.FULL_AC,
    )


def make_quiz_request() -> PersonalizedQuizRequest:
    return PersonalizedQuizRequest(
        learner_key="b" * 64,
        problem_id="problem",
        title="二つの値",
        statement="二つの整数を処理する。",
        constraints="0以上",
        learning_goal="入力を確認する",
        tags=("input",),
        source_code="print(0)",
        mode=PersonalizedQuizMode.FIXED_3,
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


def test_generate_review_uses_dedicated_endpoint_and_validates_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        text = json.dumps(
            {
                "algorithm_recap": "入力を読み、必要な処理を行います。",
                "strengths": ["処理が簡潔です。"],
                "improvements": [
                    {
                        "category": CodeReviewCategory.READABILITY.value,
                        "title": "命名",
                        "feedback": "役割が伝わる名前を維持しましょう。",
                    }
                ],
            },
            ensure_ascii=False,
        )
        return httpx.Response(200, json={"model": MODEL, "text": text})

    provider, clients = provider_with_handler(handler)

    review = provider.generate_review(make_review_request())

    assert paths == ["/v1/reviews"]
    assert review.provider == "gemma"
    assert review.improvements[0].category is CodeReviewCategory.READABILITY
    assert all(client.is_closed for client in clients)


def test_generate_quiz_uses_dedicated_endpoint_and_validates_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "text": json.dumps(
                    {
                        "questions": [
                            {
                                "focus": "edge_cases",
                                "prompt": f"境界条件 {index}",
                                "options": ["必要", "不要", "無関係"],
                                "correct_option_index": 0,
                                "explanation": "境界条件を確認するためです。",
                            }
                            for index in range(3)
                        ]
                    },
                    ensure_ascii=False,
                ),
            },
        )

    provider, _ = provider_with_handler(handler)
    quiz = provider.generate_quiz(make_quiz_request())

    assert paths == ["/v1/quizzes"]
    assert quiz.provider == "gemma"
    assert len(quiz.questions) == 3


@pytest.mark.parametrize("fence_label", ("json", "JSON", ""))
def test_generate_review_accepts_one_transport_only_json_fence(
    monkeypatch: pytest.MonkeyPatch,
    fence_label: str,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)
    payload = json.dumps(
        {
            "algorithm_recap": "入力を読み、二値を加算します。",
            "strengths": ["処理が簡潔です。"],
            "improvements": [
                {
                    "category": "readability",
                    "title": "命名",
                    "feedback": "役割が伝わる名前を維持しましょう。",
                }
            ],
        },
        ensure_ascii=False,
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"model": MODEL, "text": f"```{fence_label}\n{payload}\n```"},
        )

    provider, _ = provider_with_handler(handler)
    review = provider.generate_review(make_review_request())

    assert review.provider == "gemma"
    assert review.improvements[0].category is CodeReviewCategory.READABILITY


def test_generate_quiz_accepts_one_transport_only_json_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)
    payload = json.dumps(
        {
            "questions": [
                {
                    "focus": "edge_cases",
                    "prompt": f"境界条件 {index}",
                    "options": ["必要", "不要", "無関係"],
                    "correct_option_index": 0,
                    "explanation": "境界条件を確認するためです。",
                }
                for index in range(3)
            ]
        },
        ensure_ascii=False,
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"model": MODEL, "text": f"```json\n{payload}\n```"},
        )

    provider, _ = provider_with_handler(handler)
    quiz = provider.generate_quiz(make_quiz_request())

    assert len(quiz.questions) == 3


@pytest.mark.parametrize(
    "wrapped_text",
    (
        "Here is the JSON:\n```json\n{}\n```",
        "```json\n{}\n```\n```json\n{}\n```",
        "```json\n{\"nested\": \"```\"}\n```",
    ),
)
def test_generate_review_rejects_prose_or_multiple_fenced_documents(
    monkeypatch: pytest.MonkeyPatch,
    wrapped_text: str,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": MODEL, "text": wrapped_text})

    provider, _ = provider_with_handler(handler)

    with pytest.raises(HintProviderError) as error:
        provider.generate_review(make_review_request())

    assert error.value.reason_code is ProviderFailureReason.INVALID_STRUCTURED_RESPONSE


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


def test_doctor_generation_probe_runs_after_model_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/models":
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
        assert request.content == b""
        return httpx.Response(200, json={"model": MODEL, "ready": True})

    provider, clients = provider_with_handler(handler)

    diagnostic = provider.diagnose(generation_probe=True)

    assert diagnostic.healthy
    assert paths == ["/v1/models", "/v1/diagnostics/generation"]
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
        (502, ProviderFailureReason.PROVIDER_UNAVAILABLE, False),
        (503, ProviderFailureReason.PROVIDER_UNAVAILABLE, False),
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
    if status_code in {502, 503}:
        assert (
            raised.value.provider_detail_code
            == GemmaGenerationFailureCode.UNKNOWN_GENERATION_FAILURE.value
        )
    assert "private raw server response" not in str(raised.value)


@pytest.mark.parametrize(
    ("code", "status_code", "reason", "retryable"),
    [
        (
            "model_not_ready",
            503,
            ProviderFailureReason.PROVIDER_UNAVAILABLE,
            True,
        ),
        (
            "gpu_memory_exhausted",
            503,
            ProviderFailureReason.PROVIDER_UNAVAILABLE,
            False,
        ),
        (
            "cuda_runtime_failure",
            503,
            ProviderFailureReason.PROVIDER_UNAVAILABLE,
            False,
        ),
        (
            "device_placement_failure",
            503,
            ProviderFailureReason.PROVIDER_UNAVAILABLE,
            False,
        ),
        (
            "response_parsing_failure",
            502,
            ProviderFailureReason.INVALID_STRUCTURED_RESPONSE,
            False,
        ),
    ],
)
def test_validates_closed_server_generation_failures(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    status_code: int,
    reason: ProviderFailureReason,
    retryable: bool,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={
                "error": {
                    "code": code,
                    "retryable": retryable,
                    "request_id": "a" * 32,
                }
            },
        )

    provider, _ = provider_with_handler(handler)

    with pytest.raises(HintProviderError) as raised:
        provider.generate(make_request())

    assert raised.value.reason_code is reason
    assert raised.value.provider_detail_code == code
    assert raised.value.retryable is retryable


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, text="private html response"),
        httpx.Response(
            503,
            json={
                "error": {
                    "code": "private_unknown_code",
                    "retryable": True,
                    "request_id": "a" * 32,
                }
            },
        ),
        httpx.Response(
            503,
            json={
                "error": {
                    "code": "cuda_runtime_failure",
                    "retryable": False,
                    "request_id": "a" * 32,
                    "private_extra": "must be rejected",
                }
            },
        ),
    ],
)
def test_discards_malformed_or_unknown_server_failure_bodies(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)
    provider, _ = provider_with_handler(lambda request: response)

    with pytest.raises(HintProviderError) as raised:
        provider.generate(make_request())

    assert (
        raised.value.provider_detail_code
        == GemmaGenerationFailureCode.UNKNOWN_GENERATION_FAILURE.value
    )
    assert not raised.value.retryable
    assert "private" not in str(raised.value)


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


def test_connect_error_is_classified_as_unreachable_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private-network-detail", request=request)

    provider, _ = provider_with_handler(handler)

    with pytest.raises(HintProviderError) as raised:
        provider.generate(make_request())

    assert raised.value.reason_code is ProviderFailureReason.ENDPOINT_UNREACHABLE
    assert raised.value.retryable
    assert raised.value.exception_type == "ConnectError"
    assert "private-network-detail" not in str(raised.value)


def test_non_connect_transport_error_remains_provider_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", API_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("private-transport-detail", request=request)

    provider, _ = provider_with_handler(handler)

    with pytest.raises(HintProviderError) as raised:
        provider.generate(make_request())

    assert raised.value.reason_code is ProviderFailureReason.PROVIDER_UNAVAILABLE
    assert raised.value.retryable
    assert "private-transport-detail" not in str(raised.value)


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
