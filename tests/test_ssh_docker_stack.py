"""Docker SSH stack tests use fakes and never start containers, SSH, or a model."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
LAUNCHER = PROJECT_ROOT / "scripts" / "run-ssh-docker-stack.sh"
RELEASE_MANIFEST = PROJECT_ROOT / "config" / "gemma-server-release.conf"
EXPECTED_REMOTE_COMMIT = next(
    line.split("=", maxsplit=1)[1].strip("'")
    for line in RELEASE_MANIFEST.read_text(encoding="utf-8").splitlines()
    if line.startswith("ALGOHINT_GEMMA_SERVER_COMMIT=")
)


def write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}", encoding="utf-8")
    path.chmod(0o755)


def stack_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    calls = tmp_path / "calls"
    local_home = tmp_path / "home"
    target_dir = local_home / ".config" / "algohint"
    target_dir.mkdir(parents=True)
    target_dir.chmod(0o700)
    target = target_dir / "gemma-ssh-target"
    target.write_text("gpu-learning-host\n", encoding="ascii")
    target.chmod(0o600)
    credentials = target_dir / "gemma-remote-credentials"
    credentials.write_text(
        "ALGOHINT_GEMMA_API_KEY='private-docker-stack-marker'\n"
        "ALGOHINT_GEMMA_BACKEND='vllm'\n"
        "ALGOHINT_GEMMA_DEPLOYMENT='local'\n"
        "ALGOHINT_GEMMA_BASE_URL='https://stale.example.invalid/v1'\n",
        encoding="utf-8",
    )
    credentials.chmod(0o600)
    installed_marker = tmp_path / "installed"
    start_marker = tmp_path / "start-called"

    write_executable(
        fake_bin / "docker",
        'printf "docker %s backend=%s base=%s container_base=%s config=%s\\n" "$*" '
        '"${ALGOHINT_GEMMA_BACKEND:-}" "${ALGOHINT_GEMMA_BASE_URL:-}" '
        '"${ALGOHINT_GEMMA_CONTAINER_BASE_URL:-}" '
        '"${DOCKER_CONFIG:-}" >>"$FAKE_CALLS"\n'
        'if [[ "${1:-}" == "info" ]]; then\n'
        '  printf "%s\\n" "${FAKE_DOCKER_OS:-Linux}"\n'
        "fi\n"
        'if [[ "${1:-}" == "container" && "${2:-}" == "inspect" ]]; then\n'
        '  exit "${FAKE_LOCAL_CONTAINER_EXISTS:-1}"\n'
        "fi\n"
        'if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then exit 0; fi\n'
        'if [[ "$*" == *" run "*" doctor --provider gemma"* ]]; then\n'
        '  exit "${FAKE_DOCTOR_FAIL:-0}"\n'
        "fi\n",
    )
    write_executable(
        fake_bin / "ssh",
        'printf "ssh %s\\n" "$*" >>"$FAKE_CALLS"\n'
        'if [[ "$*" == *\'printf "%s\\n" "$HOME"\'* ]]; then\n'
        "  echo /remote/learner\n"
        'elif [[ "$*" == *"current/RELEASE"* ]]; then\n'
        '  if [[ -e "$FAKE_INSTALLED_MARKER" ]]; then\n'
        '    printf "%s\\n" "$FAKE_EXPECTED_REMOTE_COMMIT"\n'
        "  else\n"
        '    printf "%s\\n" "${FAKE_REMOTE_RELEASE:-$FAKE_EXPECTED_REMOTE_COMMIT}"\n'
        "  fi\n"
        'elif [[ "$*" == *"test -x"* ]]; then\n'
        '  if [[ -e "$FAKE_INSTALLED_MARKER" ]]; then exit 0; fi\n'
        '  exit "${FAKE_CONTROL_CHECK_EXIT:-0}"\n'
        'elif [[ "$*" == *"\'status\'"* ]]; then\n'
        '  if [[ "${FAKE_REMOTE_RUNNING:-0}" == "1" ]]; then\n'
        "    echo 'container: running'\n"
        "  else\n"
        "    echo 'container: not-running'\n"
        "  fi\n"
        'elif [[ "$*" == *"\'start\'"* && "${FAKE_START_HANG:-0}" == "1" ]]; then\n'
        '  touch "$FAKE_START_MARKER"\n'
        "  trap 'exit 130' TERM INT\n"
        "  while true; do sleep 1; done\n"
        'elif [[ " $* " == *" -N "* ]]; then\n'
        "  trap 'exit 0' TERM INT\n"
        "  while true; do sleep 1; done\n"
        "fi\n",
    )
    write_executable(fake_bin / "curl", 'printf \'{"status":"ok","ready":true}\\n\'\n')
    installer = tmp_path / "installer"
    write_executable(
        installer,
        'printf "installer\\n" >>"$FAKE_CALLS"\n'
        'if [[ "${FAKE_INSTALLER_FAIL:-0}" == "1" ]]; then exit 1; fi\n'
        'if [[ "${FAKE_INSTALLER_SKIP_UPDATE:-0}" != "1" ]]; then\n'
        '  touch "$FAKE_INSTALLED_MARKER"\n'
        "fi\n",
    )

    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HOME": str(local_home),
        "FAKE_CALLS": str(calls),
        "FAKE_EXPECTED_REMOTE_COMMIT": EXPECTED_REMOTE_COMMIT,
        "FAKE_INSTALLED_MARKER": str(installed_marker),
        "FAKE_START_MARKER": str(start_marker),
        "TMPDIR": str(tmp_path),
        "ALGOHINT_CREDENTIALS": str(credentials),
        "ALGOHINT_INSTALL_GEMMA_SERVER_SCRIPT": str(installer),
        "ALGOHINT_SSH_STARTUP_TIMEOUT": "2",
    }
    environment.pop("ALGOHINT_SSH_TARGET", None)
    environment.pop("DOCKER_CONFIG", None)
    return environment, calls


def test_stack_builds_local_and_stops_only_owned_remote(tmp_path: Path) -> None:
    environment, calls = stack_environment(tmp_path)

    completed = subprocess.run(
        [str(LAUNCHER), "--build-remote"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    output = completed.stdout + completed.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "private-docker-stack-marker" not in output + recorded
    assert "stale.example.invalid" not in output + recorded
    assert " build app" in recorded
    build_call = next(line for line in recorded.splitlines() if " build app" in line)
    build_config = Path(build_call.rsplit("config=", maxsplit=1)[1])
    assert build_config.parent == tmp_path
    assert build_config.name.startswith("algohint-public-docker.")
    assert not build_config.exists()
    doctor_call = next(
        line for line in recorded.splitlines() if " doctor --provider gemma" in line
    )
    assert doctor_call.endswith("config=")
    assert "'build'" in recorded
    assert "'start'" in recorded
    assert "'stop'" in recorded
    assert " -N -T " in f" {recorded} "
    assert " doctor --provider gemma" in recorded
    assert "--name algohint-ssh-app app" in recorded
    assert "backend=transformers_http" in recorded
    assert "base=http://127.0.0.1:18000/v1" in recorded
    assert "container_base=http://127.0.0.1:18000/v1" in recorded


def test_docker_desktop_container_uses_the_host_gateway(tmp_path: Path) -> None:
    environment, calls = stack_environment(tmp_path)
    environment["FAKE_DOCKER_OS"] = "Docker Desktop"

    completed = subprocess.run(
        [str(LAUNCHER), "--no-build-local"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert (
        "container_base=http://host.docker.internal:18000/v1"
        in recorded
    )


def test_public_docker_client_config_cannot_contain_credentials() -> None:
    config = PROJECT_ROOT / "config" / "public-docker-client" / "config.json"

    assert config.read_text(encoding="utf-8") == "{}\n"


def test_build_remote_installs_an_old_release_before_building(tmp_path: Path) -> None:
    environment, calls = stack_environment(tmp_path)
    environment["FAKE_REMOTE_RELEASE"] = "51e9a5b315256314d534a0b83b8ae38a5053b44c"
    environment["FAKE_CONTROL_CHECK_EXIT"] = "1"

    completed = subprocess.run(
        [str(LAUNCHER), "--build-remote"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert recorded.count("installer") == 1
    assert recorded.index("installer") < recorded.index(" build app")
    assert "'build'" in recorded
    assert EXPECTED_REMOTE_COMMIT in completed.stdout


def test_old_release_without_build_flag_is_not_modified(tmp_path: Path) -> None:
    environment, calls = stack_environment(tmp_path)
    old_commit = "51e9a5b315256314d534a0b83b8ae38a5053b44c"
    environment["FAKE_REMOTE_RELEASE"] = old_commit
    environment["FAKE_CONTROL_CHECK_EXIT"] = "1"

    completed = subprocess.run(
        [str(LAUNCHER), "--no-build-local"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert f"Expected commit: {EXPECTED_REMOTE_COMMIT}" in completed.stderr
    assert f"Current commit: {old_commit}" in completed.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "installer" not in recorded
    assert " build app" not in recorded
    assert "'start'" not in recorded


def test_installer_failure_stops_before_any_image_build(tmp_path: Path) -> None:
    environment, calls = stack_environment(tmp_path)
    environment["FAKE_REMOTE_RELEASE"] = "51e9a5b315256314d534a0b83b8ae38a5053b44c"
    environment["FAKE_INSTALLER_FAIL"] = "1"

    completed = subprocess.run(
        [str(LAUNCHER), "--build-remote"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 1
    recorded = calls.read_text(encoding="utf-8")
    assert recorded.count("installer") == 1
    assert " build app" not in recorded
    assert "'build'" not in recorded


def test_post_install_release_mismatch_is_rejected(tmp_path: Path) -> None:
    environment, calls = stack_environment(tmp_path)
    old_commit = "51e9a5b315256314d534a0b83b8ae38a5053b44c"
    environment["FAKE_REMOTE_RELEASE"] = old_commit
    environment["FAKE_INSTALLER_SKIP_UPDATE"] = "1"

    completed = subprocess.run(
        [str(LAUNCHER), "--build-remote"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert "did not produce the expected Docker controller" in completed.stderr
    assert f"Current commit: {old_commit}" in completed.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert " build app" not in recorded


def test_stack_preserves_a_preexisting_remote_container(tmp_path: Path) -> None:
    environment, calls = stack_environment(tmp_path)
    environment["FAKE_REMOTE_RUNNING"] = "1"

    completed = subprocess.run(
        [str(LAUNCHER), "--no-build-local"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "'start'" not in recorded
    assert "'stop'" not in recorded
    assert "Using the Gemma Docker container already running" in completed.stdout


def test_contract_failure_cleans_up_owned_remote_before_ui(tmp_path: Path) -> None:
    environment, calls = stack_environment(tmp_path)
    environment["FAKE_DOCTOR_FAIL"] = "1"

    completed = subprocess.run(
        [str(LAUNCHER), "--no-build-local"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 1
    recorded = calls.read_text(encoding="utf-8")
    assert "'start'" in recorded
    assert "'stop'" in recorded
    assert "--name algohint-ssh-app" not in recorded
    assert "contract check failed" in completed.stderr


def test_interrupt_during_remote_start_cleans_up_owned_container(
    tmp_path: Path,
) -> None:
    environment, calls = stack_environment(tmp_path)
    environment["FAKE_START_HANG"] = "1"
    start_marker = Path(environment["FAKE_START_MARKER"])

    process = subprocess.Popen(
        [str(LAUNCHER), "--no-build-local"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    deadline = time.monotonic() + 5
    while not start_marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert start_marker.exists()

    os.killpg(process.pid, signal.SIGINT)
    _, stderr = process.communicate(timeout=5)

    assert process.returncode == 130, stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "'start'" in recorded
    assert "'stop'" in recorded


def test_stack_rejects_permissive_credentials_before_remote_access(
    tmp_path: Path,
) -> None:
    environment, calls = stack_environment(tmp_path)
    Path(environment["ALGOHINT_CREDENTIALS"]).chmod(0o640)

    completed = subprocess.run(
        [str(LAUNCHER)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "must not grant group or world permissions" in completed.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "ssh " not in recorded
