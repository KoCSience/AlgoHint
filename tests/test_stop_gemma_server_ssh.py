"""Mode-neutral remote stop tests never contact SSH, Docker, or tmux."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
STOP_SCRIPT = PROJECT_ROOT / "scripts" / "stop-gemma-server-ssh.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -eu\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _environment(
    tmp_path: Path,
    *,
    native: str = "stopped",
    docker: str = "stopped",
) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    home = tmp_path / "home"
    config = home / ".config" / "algohint"
    config.mkdir(parents=True)
    config.chmod(0o700)
    target = config / "gemma-ssh-target"
    target.write_text("gpu-learning-host\n", encoding="ascii")
    target.chmod(0o600)
    _write_executable(
        fake_bin / "ssh",
        r'''
printf '%s\n' "$*" >>"$FAKE_CALLS"
if [[ "${FAKE_SSH_FAIL:-0}" == "1" ]]; then exit 255; fi
if [[ "$*" == *'printf "%s\n" "$HOME"'* ]]; then
    echo /remote/learner
elif [[ "$*" == *'bash -s --'* ]]; then
    if [[ "${FAKE_INVALID_SNAPSHOT:-0}" == "1" ]]; then
        echo 'untrusted output'
        exit 0
    fi
    native="$FAKE_NATIVE"
    docker="$FAKE_DOCKER"
    [[ -e "$FAKE_NATIVE_STOPPED" ]] && native=stopped
    [[ -e "$FAKE_DOCKER_STOPPED" ]] && docker=stopped
    health=unavailable
    if [[ "$native" == running || "$docker" == running ]]; then health=ready; fi
    printf 'release=%s\nnative=%s\ndocker=%s\nhealth=%s\n' \
      "$FAKE_RELEASE" "$native" "$docker" "$health"
elif [[ "$*" == *server-control.sh*stop ]]; then
    [[ "${FAKE_STOP_STICKS:-1}" == "0" ]] || touch "$FAKE_NATIVE_STOPPED"
elif [[ "$*" == *docker-control.sh*stop ]]; then
    [[ "${FAKE_STOP_STICKS:-1}" == "0" ]] || touch "$FAKE_DOCKER_STOPPED"
fi
''',
    )
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HOME": str(home),
        "FAKE_CALLS": str(calls),
        "FAKE_NATIVE": native,
        "FAKE_DOCKER": docker,
        "FAKE_NATIVE_STOPPED": str(tmp_path / "native-stopped"),
        "FAKE_DOCKER_STOPPED": str(tmp_path / "docker-stopped"),
        "FAKE_RELEASE": "f043147feab0fe233615447cdf156f0fb4063a88",
    }
    environment.pop("ALGOHINT_SSH_TARGET", None)
    environment.pop("ALGOHINT_SSH_REMOTE_APP_ROOT", None)
    return environment, calls


def _run(environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(STOP_SCRIPT), *arguments],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_status_reports_closed_metadata_without_stopping(tmp_path: Path) -> None:
    environment, calls = _environment(tmp_path, native="running")

    result = _run(environment, "--status")

    assert result.returncode == 0, result.stderr
    assert "native: running" in result.stdout
    assert "docker: stopped" in result.stdout
    assert " stop" not in calls.read_text(encoding="utf-8")


def test_default_stops_the_only_running_native_runtime(tmp_path: Path) -> None:
    environment, calls = _environment(tmp_path, native="running")

    result = _run(environment)

    assert result.returncode == 0, result.stderr
    assert "Managed Gemma runtime stop completed" in result.stdout
    recorded = calls.read_text(encoding="utf-8")
    assert "server-control.sh' stop" in recorded
    assert "docker-control.sh' stop" not in recorded
    assert "native: stopped" in result.stdout
    assert "healthz: unavailable" in result.stdout


def test_default_stops_the_only_running_docker_runtime(tmp_path: Path) -> None:
    environment, calls = _environment(tmp_path, docker="running")

    result = _run(environment)

    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "docker-control.sh' stop" in recorded
    assert "server-control.sh' stop" not in recorded


def test_default_refuses_ambiguous_dual_runtime_state(tmp_path: Path) -> None:
    environment, calls = _environment(tmp_path, native="running", docker="running")

    result = _run(environment)

    assert result.returncode == 2
    assert "use --all or one explicit --mode" in result.stderr
    assert " stop" not in calls.read_text(encoding="utf-8")


def test_all_stops_native_then_docker(tmp_path: Path) -> None:
    environment, calls = _environment(tmp_path, native="running", docker="running")

    result = _run(environment, "--all")

    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    native_stop = recorded.index("server-control.sh' stop")
    docker_stop = recorded.index("docker-control.sh' stop")
    assert native_stop < docker_stop
    assert "healthz: unavailable" in result.stdout


def test_explicit_mode_can_stop_one_runtime_only(tmp_path: Path) -> None:
    environment, calls = _environment(tmp_path, native="running", docker="running")

    result = _run(environment, "--mode", "docker")

    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "docker-control.sh' stop" in recorded
    assert "server-control.sh' stop" not in recorded
    assert "native: running" in result.stdout


def test_old_release_with_one_controller_can_report_already_stopped(
    tmp_path: Path,
) -> None:
    environment, calls = _environment(tmp_path, native="stopped", docker="missing")

    result = _run(environment)

    assert result.returncode == 0, result.stderr
    assert "already stopped" in result.stdout
    assert " stop" not in calls.read_text(encoding="utf-8")


def test_transport_and_contract_failures_do_not_attempt_stop(tmp_path: Path) -> None:
    for variable in ("FAKE_SSH_FAIL", "FAKE_INVALID_SNAPSHOT"):
        case_root = tmp_path / variable.lower()
        case_root.mkdir()
        environment, calls = _environment(case_root, native="running")
        environment[variable] = "1"

        result = _run(environment)

        assert result.returncode == 2
        recorded = calls.read_text(encoding="utf-8") if calls.exists() else ""
        assert " stop" not in recorded


def test_post_stop_verification_failure_is_reported(tmp_path: Path) -> None:
    environment, _ = _environment(tmp_path, native="running")
    environment["FAKE_STOP_STICKS"] = "0"

    result = _run(environment)

    assert result.returncode == 1
    assert "did not reach a verified stopped state" in result.stderr
