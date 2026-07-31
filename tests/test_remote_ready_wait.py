"""Remote readiness helper tests avoid SSH and use fake controller processes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
WAIT_HELPER = PROJECT_ROOT / "scripts" / "wait-gemma-ready-remote.sh"


def write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}", encoding="utf-8")
    path.chmod(0o755)


def helper_environment(tmp_path: Path, curl_body: str) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    write_executable(fake_bin / "curl", curl_body)
    return {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}


def test_wait_reports_progress_then_ready(tmp_path: Path) -> None:
    control = tmp_path / "control"
    calls = tmp_path / "health-calls"
    write_executable(
        control,
        'if [[ "$1" == "status" ]]; then\n'
        "  echo 'process: running (pid=12, validated)'\n"
        "  echo '  state: loading_model'\n"
        "elif [[ \"$1\" == \"logs\" ]]; then echo safe-log; fi\n",
    )
    environment = helper_environment(
        tmp_path,
        'count=0\n'
        'if [[ -r "$TEST_HEALTH_CALLS" ]]; then count="$(<"$TEST_HEALTH_CALLS")"; fi\n'
        'count=$((count + 1)); printf "%s\\n" "$count" >"$TEST_HEALTH_CALLS"\n'
        'if ((count >= 2)); then printf \'{"ready":true}\\n\'; else exit 7; fi\n',
    )
    environment["TEST_HEALTH_CALLS"] = str(calls)

    completed = subprocess.run(
        [str(WAIT_HELPER), str(control), "3", "1", "1"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "state=loading_model" in completed.stdout
    assert "is ready" in completed.stdout
    assert "Connection refused" not in completed.stdout + completed.stderr


def test_wait_fails_early_when_process_disappears(tmp_path: Path) -> None:
    control = tmp_path / "control"
    write_executable(
        control,
        'if [[ "$1" == "status" ]]; then\n'
        "  echo 'process: not-running'\n"
        "  echo '  state: loading_model'\n"
        'elif [[ "$1" == "logs" ]]; then echo safe-log-marker; fi\n',
    )
    environment = helper_environment(tmp_path, "exit 7\n")

    completed = subprocess.run(
        [str(WAIT_HELPER), str(control), "5", "1", "1"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "process exited before becoming ready" in completed.stderr
    assert "safe-log-marker" in completed.stderr


def test_wait_timeout_prints_bounded_failure_context(tmp_path: Path) -> None:
    control = tmp_path / "control"
    write_executable(
        control,
        'if [[ "$1" == "status" ]]; then\n'
        "  echo 'process: running (pid=12, validated)'\n"
        "  echo '  state: loading_model'\n"
        'elif [[ "$1" == "logs" ]]; then echo safe-log-marker; fi\n',
    )
    environment = helper_environment(tmp_path, "exit 7\n")

    completed = subprocess.run(
        [str(WAIT_HELPER), str(control), "2", "1", "1"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "did not become ready within 2s" in completed.stderr
    assert "safe-log-marker" in completed.stderr
