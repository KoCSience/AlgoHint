"""HTTP contract tests use a fake runtime and never download model weights."""

import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient

from algohint_gemma_server.app import create_app
from algohint_gemma_server.config import ServerConfig
from algohint_gemma_server.model_runtime import InvalidModelOutputError

API_KEY = "test-only-api-key-that-is-long-enough"
AUTHORIZATION = {"Authorization": f"Bearer {API_KEY}"}


class FakeRuntime:
    """Deterministic runtime that records no request content."""

    def __init__(self, text: str = "次に境界条件を小さな入力で確認しましょう。") -> None:
        self.text = text
        self.loaded = False
        self.generate_calls = 0

    @property
    def ready(self) -> bool:
        return self.loaded

    def load(self) -> None:
        self.loaded = True

    def generate(
        self,
        system_instructions: str,
        learner_context: str,
        *,
        max_output_chars: int = 1_200,
        max_new_tokens: int | None = None,
    ) -> str:
        self.generate_calls += 1
        return self.text


def config() -> ServerConfig:
    return ServerConfig(
        model_id="google/gemma-4-12B-it",
        model_revision="test-revision",
        api_key=API_KEY,
    )


def client_for(runtime: FakeRuntime) -> TestClient:
    return TestClient(create_app(config=config(), runtime_factory=lambda _: runtime))


def test_health_and_authenticated_model_discovery() -> None:
    runtime = FakeRuntime()
    with client_for(runtime) as client:
        health = client.get("/healthz")
        unauthorized = client.get("/v1/models")
        models = client.get("/v1/models", headers=AUTHORIZATION)

    assert health.json() == {"status": "ok", "ready": True}
    assert unauthorized.status_code == 401
    assert models.json() == {
        "data": [
            {
                "id": "google/gemma-4-12B-it",
                "revision": "test-revision",
                "backend": "transformers",
                "ready": True,
            }
        ]
    }


def test_hint_endpoint_returns_server_owned_json_contract() -> None:
    runtime = FakeRuntime()
    with client_for(runtime) as client:
        response = client.post(
            "/v1/hints",
            headers=AUTHORIZATION,
            json={
                "model": "google/gemma-4-12B-it",
                "system_instructions": "trusted system",
                "learner_context": "untrusted learner context",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "model": "google/gemma-4-12B-it",
        "text": "次に境界条件を小さな入力で確認しましょう。",
    }
    assert runtime.generate_calls == 1


def test_review_endpoint_uses_same_authenticated_bounded_runtime() -> None:
    runtime = FakeRuntime(text='{"algorithm_recap":"review"}')
    with client_for(runtime) as client:
        response = client.post(
            "/v1/reviews",
            headers=AUTHORIZATION,
            json={
                "model": "google/gemma-4-12B-it",
                "system_instructions": "trusted review system",
                "learner_context": "untrusted source context",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "model": "google/gemma-4-12B-it",
        "text": '{"algorithm_recap":"review"}',
    }
    assert runtime.generate_calls == 1


def test_quiz_endpoint_uses_dedicated_bounded_contract() -> None:
    runtime = FakeRuntime(text='{"questions":[]}')
    with client_for(runtime) as client:
        response = client.post(
            "/v1/quizzes",
            headers=AUTHORIZATION,
            json={
                "model": "google/gemma-4-12B-it",
                "system_instructions": "trusted quiz system",
                "learner_context": "untrusted accepted source context",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "model": "google/gemma-4-12B-it",
        "text": '{"questions":[]}',
    }
    assert runtime.generate_calls == 1


def test_hint_endpoint_rejects_unknown_model_and_oversized_fields() -> None:
    runtime = FakeRuntime()
    with client_for(runtime) as client:
        missing = client.post(
            "/v1/hints",
            headers=AUTHORIZATION,
            json={
                "model": "other/model",
                "system_instructions": "trusted",
                "learner_context": "context",
            },
        )
        oversized = client.post(
            "/v1/hints",
            headers=AUTHORIZATION,
            json={
                "model": "google/gemma-4-12B-it",
                "system_instructions": "trusted",
                "learner_context": "x" * 65_537,
            },
        )

    assert missing.status_code == 404
    assert oversized.status_code == 422
    assert runtime.generate_calls == 0


def test_declared_oversized_body_is_rejected_before_parsing() -> None:
    with client_for(FakeRuntime()) as client:
        response = client.post(
            "/v1/hints",
            headers={**AUTHORIZATION, "Content-Length": "98305"},
            content=b"{}",
        )

    assert response.status_code == 413


def test_parallel_generation_is_rejected_without_queueing() -> None:
    entered = Event()
    release = Event()

    class BlockingRuntime(FakeRuntime):
        def generate(
            self,
            system_instructions: str,
            learner_context: str,
            *,
            max_output_chars: int = 1_200,
            max_new_tokens: int | None = None,
        ) -> str:
            entered.set()
            assert release.wait(timeout=5)
            return self.text

    runtime = BlockingRuntime()
    payload = {
        "model": "google/gemma-4-12B-it",
        "system_instructions": "trusted",
        "learner_context": "context",
    }
    with client_for(runtime) as client, ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            client.post,
            "/v1/hints",
            headers=AUTHORIZATION,
            json=payload,
        )
        assert entered.wait(timeout=5)
        second = client.post("/v1/hints", headers=AUTHORIZATION, json=payload)
        release.set()
        completed = first.result(timeout=5)

    assert second.status_code == 429
    assert completed.status_code == 200


def test_invalid_runtime_output_is_a_safe_bad_gateway() -> None:
    class InvalidRuntime(FakeRuntime):
        def generate(
            self,
            system_instructions: str,
            learner_context: str,
            *,
            max_output_chars: int = 1_200,
            max_new_tokens: int | None = None,
        ) -> str:
            raise InvalidModelOutputError("private generated output")

    with client_for(InvalidRuntime()) as client:
        response = client.post(
            "/v1/hints",
            headers=AUTHORIZATION,
            json={
                "model": "google/gemma-4-12B-it",
                "system_instructions": "trusted",
                "learner_context": "private learner marker",
            },
        )

    assert response.status_code == 502
    assert "private generated output" not in response.text
    assert "private learner marker" not in response.text


def test_server_logs_never_include_request_or_key(
    caplog,
) -> None:
    private_prompt = "private-learner-prompt-marker"
    with (
        caplog.at_level(logging.INFO, logger="algohint_gemma_server.app"),
        client_for(FakeRuntime()) as client,
    ):
        response = client.post(
            "/v1/hints",
            headers=AUTHORIZATION,
            json={
                    "model": "google/gemma-4-12B-it",
                "system_instructions": "trusted",
                "learner_context": private_prompt,
            },
        )

    assert response.status_code == 200
    assert "gemma_inference_complete" in caplog.text
    assert private_prompt not in caplog.text
    assert API_KEY not in caplog.text
