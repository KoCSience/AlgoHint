"""Portable launcher tests use fakes so no UI, SSH, tmux, or model is started."""

import os
import signal
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -eu\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _stack_fakes(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls"
    control = tmp_path / "gemma-control"
    runner = tmp_path / "algohint-runner"
    _write_executable(
        control,
        """
printf 'control %s app_root=%s code_root=%s\\n' \
  "$*" "${ALGOHINT_GEMMA_APP_ROOT:-}" "${ALGOHINT_GEMMA_CODE_ROOT:-}" \
  >>"$FAKE_CALLS"
if [[ "${1:-}" == "status" ]]; then
    if [[ "${FAKE_GEMMA_RUNNING:-0}" == "1" ]]; then
        echo 'process: running (pid=12, validated)'
    else
        echo 'process: not-running'
    fi
fi
""",
    )
    _write_executable(
        runner,
        """
printf 'app %s backend=%s deployment=%s base=%s\\n' \
  "$*" "${ALGOHINT_GEMMA_BACKEND:-}" "${ALGOHINT_GEMMA_DEPLOYMENT:-}" \
  "${ALGOHINT_GEMMA_BASE_URL:-}" >>"$FAKE_CALLS"
if [[ "${FAKE_APP_BLOCK:-0}" == "1" ]]; then
    trap 'exit 0' TERM INT
    while true; do sleep 1; done
fi
""",
    )
    _write_executable(fake_bin / "curl", "printf '{\"status\":\"ok\",\"ready\":true}\\n'\n")
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_CALLS": str(calls),
        "ALGOHINT_LOCAL_GEMMA_CONTROL": str(control),
        "ALGOHINT_RUN_ALGOHINT_SCRIPT": str(runner),
        "ALGOHINT_GEMMA_STARTUP_TIMEOUT": "2",
    }
    return environment, calls


def test_all_launchers_parse_as_bash() -> None:
    paths = [
        SCRIPTS / "run-algohint.sh",
        SCRIPTS / "run-local-stack.sh",
        SCRIPTS / "run-ssh-stack.sh",
        SCRIPTS / "bootstrap-gemma-server-remote.sh",
        SCRIPTS / "install-gemma-server-ssh.sh",
        SCRIPTS / "sync-gemma-credentials-ssh.sh",
    ]
    result = subprocess.run(
        ["bash", "-n", *(str(path) for path in paths)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_algohint_launcher_uses_script_root_and_configured_credentials(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "uv-calls"
    fake_uv = tmp_path / "uv"
    credentials = tmp_path / "credentials"
    credentials.write_text(
        "ALGOHINT_ENV='development'\n"
        "OPENAI_API_KEY='private-launcher-secret-marker'\n",
        encoding="utf-8",
    )
    _write_executable(
        fake_uv,
        """
printf '%s env=%s\\n' "$*" "${ALGOHINT_ENV:-}" >"$FAKE_UV_CALLS"
""",
    )

    result = subprocess.run(
        [str(SCRIPTS / "run-algohint.sh"), "--port", "9786"],
        cwd=tmp_path,
        env={
            **os.environ,
            "ALGOHINT_UV_BIN": str(fake_uv),
            "ALGOHINT_CREDENTIALS": str(credentials),
            "FAKE_UV_CALLS": str(calls),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    invocation = calls.read_text(encoding="utf-8")
    assert "run --frozen --no-sync algohint --data-dir" in invocation
    assert str(PROJECT_ROOT / "data") in invocation
    assert "--port 9786" in invocation
    assert "env=development" in invocation
    assert "private-launcher-secret-marker" not in invocation
    assert "private-launcher-secret-marker" not in result.stdout + result.stderr


def test_local_stack_stops_only_gemma_it_started(tmp_path: Path) -> None:
    environment, calls = _stack_fakes(tmp_path)

    started = subprocess.run(
        [str(SCRIPTS / "run-local-stack.sh"), "--port", "9786"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert started.returncode == 0, started.stderr
    first_calls = calls.read_text(encoding="utf-8")
    assert "control start" in first_calls
    assert "control stop" in first_calls
    assert "deployment=local" in first_calls
    assert "app_root= code_root=" in first_calls

    calls.write_text("", encoding="utf-8")
    existing_environment = {**environment, "FAKE_GEMMA_RUNNING": "1"}
    existing = subprocess.run(
        [str(SCRIPTS / "run-local-stack.sh")],
        env=existing_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert existing.returncode == 0, existing.stderr
    second_calls = calls.read_text(encoding="utf-8")
    assert "control start" not in second_calls
    assert "control stop" not in second_calls


def test_local_keep_flag_preserves_new_server(tmp_path: Path) -> None:
    environment, calls = _stack_fakes(tmp_path)

    result = subprocess.run(
        [str(SCRIPTS / "run-local-stack.sh"), "--keep-gemma"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "control start" in recorded
    assert "control stop" not in recorded


def test_local_stack_requires_standalone_server_install(tmp_path: Path) -> None:
    environment, calls = _stack_fakes(tmp_path)
    environment.pop("ALGOHINT_LOCAL_GEMMA_CONTROL")
    environment["ALGOHINT_GEMMA_INSTALL_ROOT"] = str(tmp_path / "missing-server")

    result = subprocess.run(
        [str(SCRIPTS / "run-local-stack.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Standalone Gemma Server control script is missing" in result.stderr
    assert "Install the pinned release" in result.stderr
    assert not calls.exists()


def test_local_stack_ctrl_c_stops_owned_children(tmp_path: Path) -> None:
    environment, calls = _stack_fakes(tmp_path)
    environment["FAKE_APP_BLOCK"] = "1"
    process = subprocess.Popen(
        [str(SCRIPTS / "run-local-stack.sh")],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(50):
            if calls.exists() and "app " in calls.read_text(encoding="utf-8"):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("fake AlgoHint process did not start")
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert process.returncode == 130, (stdout, stderr)
    assert "control stop" in calls.read_text(encoding="utf-8")


def _ssh_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "ssh-bin"
    fake_bin.mkdir()
    calls = tmp_path / "ssh-calls"
    runner = tmp_path / "ssh-algohint-runner"
    _write_executable(
        runner,
        """
printf 'app backend=%s deployment=%s base=%s\\n' \
  "${ALGOHINT_GEMMA_BACKEND:-}" "${ALGOHINT_GEMMA_DEPLOYMENT:-}" \
  "${ALGOHINT_GEMMA_BASE_URL:-}" >>"$FAKE_CALLS"
""",
    )
    _write_executable(
        fake_bin / "ssh",
        """
printf 'ssh %s\\n' "$*" >>"$FAKE_CALLS"
if [[ "$*" == *'printf \"%s\\n\" \"$HOME\"'* ]]; then
    echo '/remote/learner'
elif [[ "$*" == *'test -x '* ]]; then
    exit "${FAKE_CONTROL_CHECK_EXIT:-0}"
elif [[ "$*" == *\"'status'\"* ]]; then
    if [[ "${FAKE_REMOTE_RUNNING:-0}" == "1" ]]; then
        echo 'process: running (pid=34, validated)'
    else
        echo 'process: not-running'
    fi
elif [[ " $* " == *' -N '* ]]; then
    trap 'exit 0' TERM INT
    while true; do sleep 1; done
fi
""",
    )
    _write_executable(fake_bin / "curl", "printf '{\"status\":\"ok\",\"ready\":true}\\n'\n")
    return (
        {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_CALLS": str(calls),
            "ALGOHINT_RUN_ALGOHINT_SCRIPT": str(runner),
            "ALGOHINT_SSH_TARGET": "gpu-learning-host",
            "ALGOHINT_SSH_STARTUP_TIMEOUT": "2",
        },
        calls,
    )


def test_ssh_stack_starts_tunnels_and_stops_owned_remote(tmp_path: Path) -> None:
    environment, calls = _ssh_environment(tmp_path)

    result = subprocess.run(
        [str(SCRIPTS / "run-ssh-stack.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "/remote/learner/programs/algohint-gemma-server" in recorded
    assert "ALGOHINT_GEMMA_INSTALL_ROOT=" in recorded
    assert "ALGOHINT_GEMMA_APP_ROOT=" not in recorded
    assert "'start'" in recorded
    assert " -N -T " in f" {recorded} "
    assert "'stop'" in recorded
    assert "deployment=remote" in recorded
    assert "base=http://127.0.0.1:18000/v1" in recorded


def test_ssh_stack_fails_before_start_when_remote_control_is_missing(
    tmp_path: Path,
) -> None:
    environment, calls = _ssh_environment(tmp_path)
    environment["FAKE_CONTROL_CHECK_EXIT"] = "1"

    result = subprocess.run(
        [str(SCRIPTS / "run-ssh-stack.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "control script is missing or not executable" in result.stderr
    assert (
        "/remote/learner/programs/algohint-gemma-server/current/"
        "scripts/server-control.sh"
    ) in result.stderr
    assert "https://github.com/KoCSience/AlgoHint-Gemma-Server" in result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "'status'" not in recorded
    assert "'start'" not in recorded
    assert " -N -T " not in f" {recorded} "
    assert "app " not in recorded


def test_ssh_stack_reports_control_probe_transport_failure(tmp_path: Path) -> None:
    environment, calls = _ssh_environment(tmp_path)
    environment["FAKE_CONTROL_CHECK_EXIT"] = "255"

    result = subprocess.run(
        [str(SCRIPTS / "run-ssh-stack.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "Could not verify" in result.stderr
    assert "Target: gpu-learning-host" in result.stderr
    assert "Expected path:" not in result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "'status'" not in recorded
    assert "'start'" not in recorded
    assert " -N -T " not in f" {recorded} "
    assert "app " not in recorded


def test_ssh_stack_rejects_unsafe_remote_path_overrides(tmp_path: Path) -> None:
    overrides = {
        "ALGOHINT_SSH_REMOTE_APP_ROOT": "remote_app_root",
        "ALGOHINT_SSH_REMOTE_CONTROL": "remote_control",
    }

    for environment_name, shell_name in overrides.items():
        case_root = tmp_path / environment_name.lower()
        case_root.mkdir()
        environment, calls = _ssh_environment(case_root)
        environment[environment_name] = "/remote/valid\ninjected"

        result = subprocess.run(
            [str(SCRIPTS / "run-ssh-stack.sh")],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 2
        assert f"{shell_name} must be one non-empty remote path" in result.stderr
        recorded = calls.read_text(encoding="utf-8") if calls.exists() else ""
        assert "test -x" not in recorded
        assert "'status'" not in recorded
        assert "'start'" not in recorded
        assert " -N -T " not in f" {recorded} "
        assert "app " not in recorded


def test_ssh_keep_flag_preserves_new_remote(tmp_path: Path) -> None:
    environment, calls = _ssh_environment(tmp_path)

    result = subprocess.run(
        [str(SCRIPTS / "run-ssh-stack.sh"), "--keep-remote"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "'start'" in recorded
    assert "'stop'" not in recorded


def test_ssh_stack_does_not_stop_preexisting_remote(tmp_path: Path) -> None:
    environment, calls = _ssh_environment(tmp_path)
    environment["FAKE_REMOTE_RUNNING"] = "1"

    result = subprocess.run(
        [str(SCRIPTS / "run-ssh-stack.sh")],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "'start'" not in recorded
    assert "'stop'" not in recorded
