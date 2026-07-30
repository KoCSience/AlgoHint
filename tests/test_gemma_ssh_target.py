"""SSH target tests use temporary homes and never contact a real host."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = PROJECT_ROOT / "scripts" / "check-gemma-ssh.sh"


def write_executable(path: Path, body: str) -> None:
    """Create an executable test double with strict shell behavior."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}", encoding="utf-8")
    path.chmod(0o755)


def write_target(home: Path, content: str = "gpu-test-host\n") -> Path:
    """Create the protected local SSH target fixture."""

    target_path = home / ".config" / "algohint" / "gemma-ssh-target"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.parent.chmod(0o700)
    target_path.write_text(content, encoding="utf-8")
    target_path.chmod(0o600)
    return target_path


def check_environment(
    tmp_path: Path,
    *,
    ssh_body: str = 'printf "%s\\n" "$*" >>"$SSH_CALLS"\n',
) -> tuple[dict[str, str], Path, Path]:
    """Build an isolated local config and fake SSH executable."""

    home = tmp_path / "home"
    home.mkdir()
    target_path = write_target(home)
    fake_bin = tmp_path / "bin"
    calls = tmp_path / "ssh-calls"
    write_executable(fake_bin / "ssh", ssh_body)
    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SSH_CALLS": str(calls),
    }
    environment.pop("ALGOHINT_SSH_TARGET", None)
    return environment, target_path, calls


def test_check_uses_configured_target_and_prints_success_locally(
    tmp_path: Path,
) -> None:
    environment, _, calls = check_environment(tmp_path)

    completed = subprocess.run(
        [str(CHECK_SCRIPT)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert calls.read_text(encoding="utf-8") == "-T gpu-test-host true\n"
    assert completed.stdout == (
        "SSH connection OK: AlgoHint host -> GPU host (target: gpu-test-host)\n"
    )
    assert "printf" not in calls.read_text(encoding="utf-8")


def test_check_preserves_ssh_failure_without_printing_success(tmp_path: Path) -> None:
    environment, _, _ = check_environment(tmp_path, ssh_body="exit 23\n")

    completed = subprocess.run(
        [str(CHECK_SCRIPT)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 23
    assert "SSH connection OK" not in completed.stdout
    assert "connection check failed" in completed.stderr
    assert "gpu-test-host" in completed.stderr


def test_check_rejects_arguments_before_ssh(tmp_path: Path) -> None:
    environment, _, calls = check_environment(tmp_path)

    completed = subprocess.run(
        [str(CHECK_SCRIPT), "unexpected"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "Usage:" in completed.stderr
    assert not calls.exists()


@pytest.mark.parametrize(
    ("content", "expected_error"),
    [
        ("", "1 to 255"),
        ("first\nsecond\n", "exactly one"),
        ("host name\n", "ASCII letters"),
        ("user@host\n", "ASCII letters"),
        ("-unsafe\n", "must not begin"),
        ("a" * 256, "1 to 255"),
    ],
)
def test_check_rejects_invalid_target_content_before_ssh(
    tmp_path: Path,
    content: str,
    expected_error: str,
) -> None:
    environment, target_path, calls = check_environment(tmp_path)
    target_path.write_text(content, encoding="utf-8")
    target_path.chmod(0o600)

    completed = subprocess.run(
        [str(CHECK_SCRIPT)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert expected_error in completed.stderr
    assert not calls.exists()


def test_check_rejects_missing_target_before_ssh(tmp_path: Path) -> None:
    environment, target_path, calls = check_environment(tmp_path)
    target_path.unlink()

    completed = subprocess.run(
        [str(CHECK_SCRIPT)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "file is missing" in completed.stderr
    assert not calls.exists()


def test_check_reports_missing_configuration_directory_before_ssh(
    tmp_path: Path,
) -> None:
    environment, target_path, calls = check_environment(tmp_path)
    target_path.unlink()
    target_path.parent.rmdir()

    completed = subprocess.run(
        [str(CHECK_SCRIPT)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "directory is missing" in completed.stderr
    assert "mode 700" in completed.stderr
    assert not calls.exists()


def test_check_rejects_target_symlink_before_ssh(tmp_path: Path) -> None:
    environment, target_path, calls = check_environment(tmp_path)
    outside = tmp_path / "outside-target"
    outside.write_text("gpu-test-host\n", encoding="ascii")
    target_path.unlink()
    target_path.symlink_to(outside)

    completed = subprocess.run(
        [str(CHECK_SCRIPT)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "regular non-symlink" in completed.stderr
    assert not calls.exists()


def test_check_rejects_target_with_nonprivate_mode_before_ssh(
    tmp_path: Path,
) -> None:
    environment, target_path, calls = check_environment(tmp_path)
    target_path.chmod(0o644)

    completed = subprocess.run(
        [str(CHECK_SCRIPT)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "mode 600" in completed.stderr
    assert not calls.exists()


def test_check_rejects_nonprivate_configuration_directory_before_ssh(
    tmp_path: Path,
) -> None:
    environment, target_path, calls = check_environment(tmp_path)
    target_path.parent.chmod(0o755)

    completed = subprocess.run(
        [str(CHECK_SCRIPT)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "mode 700" in completed.stderr
    assert not calls.exists()


def test_check_rejects_target_owned_by_another_user_before_ssh(
    tmp_path: Path,
) -> None:
    environment, target_path, calls = check_environment(tmp_path)
    fake_stat = Path(environment["PATH"].split(":", maxsplit=1)[0]) / "stat"
    write_executable(
        fake_stat,
        f'if [[ "${{2:-}}" == "%u %a %s" && "${{3:-}}" == "{target_path}" ]]; then\n'
        '  printf "999999 600 14\\n"\n'
        "else\n"
        '  exec /usr/bin/stat "$@"\n'
        "fi\n",
    )

    completed = subprocess.run(
        [str(CHECK_SCRIPT)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "owned by the current user" in completed.stderr
    assert not calls.exists()


def test_check_rejects_removed_environment_even_with_valid_file(
    tmp_path: Path,
) -> None:
    environment, _, calls = check_environment(tmp_path)
    environment["ALGOHINT_SSH_TARGET"] = ""

    completed = subprocess.run(
        [str(CHECK_SCRIPT)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "is no longer supported" in completed.stderr
    assert "unset ALGOHINT_SSH_TARGET" in completed.stderr
    assert not calls.exists()
