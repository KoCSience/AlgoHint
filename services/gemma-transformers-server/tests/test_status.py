"""Runtime status tests cover atomicity, closed fields, and lifecycle states."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from algohint_gemma_server.app import create_app
from algohint_gemma_server.config import ServerConfig
from algohint_gemma_server.status import RuntimeStatusReporter

API_KEY = "test-only-api-key-that-is-long-enough"


class ReadyRuntime:
    """Small lifecycle fake that never retains generation input."""

    ready = False

    def load(self) -> None:
        self.ready = True

    def generate(
        self,
        system_instructions: str,
        learner_context: str,
        *,
        max_output_chars: int = 1_200,
        max_new_tokens: int | None = None,
    ) -> str:
        return "safe output"


def _config() -> ServerConfig:
    return ServerConfig(
        model_id="google/gemma-4-12B-it",
        model_revision="test-revision",
        api_key=API_KEY,
    )


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_reporter_replaces_json_atomically_with_closed_fields(tmp_path: Path) -> None:
    status_path = tmp_path / "state" / "status.json"
    reporter = RuntimeStatusReporter(
        status_path,
        model_id="model",
        revision="revision",
        pid=123,
    )

    reporter.update("generating_quiz", request_kind="quiz", elapsed_ms=8)

    assert _read(status_path) == {
        "elapsed_ms": 8,
        "model_id": "model",
        "pid": 123,
        "request_kind": "quiz",
        "revision": "revision",
        "state": "generating_quiz",
        "updated_at": _read(status_path)["updated_at"],
    }
    assert not list(status_path.parent.glob("*.tmp"))
    assert status_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        reporter.update("secret-state")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        reporter.update("failed", exception_type="unsafe exception text")


def test_app_reports_ready_generation_and_stopped_states(tmp_path: Path) -> None:
    status_path = tmp_path / "status.json"
    reporter = RuntimeStatusReporter(
        status_path,
        model_id="google/gemma-4-12B-it",
        revision="test-revision",
    )
    app = create_app(
        config=_config(),
        runtime_factory=lambda _: ReadyRuntime(),
        status_reporter=reporter,
    )

    with TestClient(app) as client:
        assert _read(status_path)["state"] == "ready"
        response = client.post(
            "/v1/quizzes",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": "google/gemma-4-12B-it",
                "system_instructions": "private system",
                "learner_context": "private accepted source",
            },
        )
        current = _read(status_path)
        assert response.status_code == 200
        assert current["state"] == "ready"
        assert current["request_kind"] == "quiz"
        assert isinstance(current["elapsed_ms"], int)
        assert "private" not in status_path.read_text(encoding="utf-8")

    assert _read(status_path)["state"] == "stopped"


def test_startup_failure_records_only_exception_class(tmp_path: Path) -> None:
    class FailingRuntime(ReadyRuntime):
        def load(self) -> None:
            raise RuntimeError("private model cache location")

    status_path = tmp_path / "status.json"
    reporter = RuntimeStatusReporter(
        status_path,
        model_id="model",
        revision="revision",
    )
    app = create_app(
        config=_config(),
        runtime_factory=lambda _: FailingRuntime(),
        status_reporter=reporter,
    )

    with pytest.raises(RuntimeError), TestClient(app):
        pass

    raw = status_path.read_text(encoding="utf-8")
    assert _read(status_path)["state"] == "failed"
    assert _read(status_path)["exception_type"] == "RuntimeError"
    assert "private model cache location" not in raw


def test_in_flight_request_exposes_safe_generating_state(tmp_path: Path) -> None:
    entered = Event()
    release = Event()

    class BlockingRuntime(ReadyRuntime):
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
            return "safe output"

    status_path = tmp_path / "status.json"
    reporter = RuntimeStatusReporter(
        status_path,
        model_id="model",
        revision="revision",
    )
    app = create_app(
        config=_config(),
        runtime_factory=lambda _: BlockingRuntime(),
        status_reporter=reporter,
    )
    payload = {
        "model": "google/gemma-4-12B-it",
        "system_instructions": "private system",
        "learner_context": "private learner context",
    }

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            client.post,
            "/v1/hints",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json=payload,
        )
        assert entered.wait(timeout=5)
        current = _read(status_path)
        assert current["state"] == "generating_hint"
        assert current["request_kind"] == "hint"
        release.set()
        assert future.result(timeout=5).status_code == 200


def test_abnormal_wrapper_exit_does_not_overwrite_orderly_stop(tmp_path: Path) -> None:
    status_path = tmp_path / "status.json"
    reporter = RuntimeStatusReporter(
        status_path,
        model_id="model",
        revision="revision",
    )

    reporter.update("ready")
    reporter.mark_process_exit(1)
    assert _read(status_path)["state"] == "failed"

    reporter.update("stopped")
    reporter.mark_process_exit(143)
    assert _read(status_path)["state"] == "stopped"
