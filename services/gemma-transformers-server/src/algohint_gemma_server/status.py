"""Secret-free runtime status persisted atomically for operator monitoring."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Literal

RuntimeState = Literal[
    "starting",
    "loading_processor",
    "loading_model",
    "ready",
    "generating_hint",
    "generating_review",
    "generating_quiz",
    "ready_with_last_error",
    "stopping",
    "stopped",
    "failed",
]
RequestKind = Literal["hint", "review", "quiz"]

ALLOWED_STATES = frozenset(
    {
        "starting",
        "loading_processor",
        "loading_model",
        "ready",
        "generating_hint",
        "generating_review",
        "generating_quiz",
        "ready_with_last_error",
        "stopping",
        "stopped",
        "failed",
    }
)
ALLOWED_REQUEST_KINDS = frozenset({"hint", "review", "quiz"})


class RuntimeStatusReporter:
    """Write only closed, non-sensitive operational metadata.

    The reporter deliberately accepts no free-form message or exception object,
    preventing prompts, source code, credentials, and provider output from
    crossing into the status file.
    """

    def __init__(
        self,
        path: Path | None,
        *,
        model_id: str,
        revision: str,
        pid: int | None = None,
    ) -> None:
        self._path = path
        self._model_id = model_id
        self._revision = revision
        self._pid = pid or os.getpid()
        self._lock = Lock()

    @classmethod
    def from_environment(
        cls,
        *,
        model_id: str,
        revision: str,
    ) -> RuntimeStatusReporter:
        """Create a reporter without reading credentials or dotenv files."""

        raw_path = os.environ.get("ALGOHINT_GEMMA_STATUS_FILE", "").strip()
        return cls(
            Path(raw_path).expanduser() if raw_path else None,
            model_id=model_id,
            revision=revision,
        )

    def update(
        self,
        state: RuntimeState,
        *,
        request_kind: RequestKind | None = None,
        elapsed_ms: int | None = None,
        exception_type: str | None = None,
    ) -> None:
        """Atomically replace the report after validating every variable field."""

        if state not in ALLOWED_STATES:
            raise ValueError("unsupported Gemma runtime state")
        if request_kind is not None and request_kind not in ALLOWED_REQUEST_KINDS:
            raise ValueError("unsupported Gemma request kind")
        if elapsed_ms is not None and elapsed_ms < 0:
            raise ValueError("elapsed_ms must not be negative")
        if exception_type is not None and (
            not exception_type.isidentifier() or len(exception_type) > 100
        ):
            raise ValueError("exception_type must be a bounded class name")
        if self._path is None:
            return

        payload: dict[str, str | int] = {
            "state": state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "pid": self._pid,
            "model_id": self._model_id,
            "revision": self._revision,
        }
        if request_kind is not None:
            payload["request_kind"] = request_kind
        if elapsed_ms is not None:
            payload["elapsed_ms"] = elapsed_ms
        if exception_type is not None:
            payload["exception_type"] = exception_type

        with self._lock:
            self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self._path.with_name(
                f".{self._path.name}.{self._pid}.tmp"
            )
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.chmod(0o600)
            os.replace(temporary, self._path)

    def mark_process_exit(self, exit_code: int) -> None:
        """Preserve an orderly stop, otherwise expose an abnormal process exit."""

        if self._path is not None and self._path.exists():
            try:
                current = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                current = {}
            if current.get("state") in {"stopping", "stopped"}:
                return
        if exit_code != 0:
            self.update("failed", exception_type="ProcessExit")


def _main() -> int:
    """Allow the shell wrapper to record an abnormal Uvicorn process exit."""

    if len(sys.argv) != 3 or sys.argv[1] != "process-exit":
        return 2
    try:
        exit_code = int(sys.argv[2])
    except ValueError:
        return 2
    reporter = RuntimeStatusReporter.from_environment(
        model_id=os.environ.get("ALGOHINT_GEMMA_MODEL", "unknown"),
        revision=os.environ.get("ALGOHINT_GEMMA_MODEL_REVISION", "unknown"),
    )
    reporter.mark_process_exit(exit_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
