"""Credential synchronization tests keep all remote secrets inside fixtures."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = PROJECT_ROOT / "scripts" / "sync-gemma-credentials-ssh.sh"
API_KEY = "fixture-only-gemma-api-key-with-sufficient-length"


def write_executable(path: Path, body: str) -> None:
    """Create an executable test double with strict shell behavior."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}", encoding="utf-8")
    path.chmod(0o755)


def write_ssh_target(home: Path, target: str = "gpu-test-host") -> None:
    """Create the protected one-line SSH target consumed by public scripts."""

    target_path = home / ".config" / "algohint" / "gemma-ssh-target"
    target_path.parent.mkdir(parents=True)
    target_path.parent.chmod(0o700)
    target_path.write_text(f"{target}\n", encoding="ascii")
    target_path.chmod(0o600)


def remote_credentials(home: Path, *, mode: int = 0o600) -> Path:
    """Create a protected remote fixture containing client and server-only values."""

    credentials = home / ".config" / "algohint-gemma-server" / "credentials"
    credentials.parent.mkdir(parents=True, exist_ok=True)
    credentials.write_text(
        "\n".join(
            (
                f"ALGOHINT_GEMMA_API_KEY={API_KEY}",
                "EXA_API_KEY=server-only-exa-search-key",
                "HF_TOKEN=server-only-hugging-face-token",
                "ALGOHINT_GEMMA_MODEL_REVISION=server-only-legacy-revision",
                "",
            )
        ),
        encoding="utf-8",
    )
    credentials.chmod(mode)
    return credentials


def environment(tmp_path: Path, *, ssh_body: str | None = None) -> dict[str, str]:
    """Build a fake SSH boundary that executes or tampers with the remote script."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    remote_home = tmp_path / "remote-home"
    remote_home.mkdir()
    local_home = tmp_path / "local-home"
    local_home.mkdir()
    write_ssh_target(local_home)
    remote_credentials(remote_home)
    body = ssh_body or (
        'export HOME="$FAKE_REMOTE_HOME"\n'
        'unset XDG_CONFIG_HOME\n'
        "exec bash -s\n"
    )
    write_executable(fake_bin / "ssh", body)
    resolved_environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HOME": str(local_home),
        "FAKE_REMOTE_HOME": str(remote_home),
    }
    resolved_environment.pop("ALGOHINT_SSH_TARGET", None)
    return resolved_environment


def run_sync(
    tmp_path: Path,
    *arguments: str,
    ssh_body: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the public helper and return its dedicated local credentials path."""

    resolved_environment = environment(tmp_path, ssh_body=ssh_body)
    completed = subprocess.run(
        [str(SYNC_SCRIPT), *arguments],
        env=resolved_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    credentials = (
        Path(resolved_environment["HOME"])
        / ".config"
        / "algohint"
        / "gemma-remote-credentials"
    )
    return completed, credentials


def test_sync_copies_only_api_key_with_private_permissions(tmp_path: Path) -> None:
    completed, credentials = run_sync(tmp_path)

    assert completed.returncode == 0
    assert credentials.read_text(encoding="utf-8") == (
        f"ALGOHINT_GEMMA_API_KEY={API_KEY}\n"
    )
    assert credentials.stat().st_mode & 0o777 == 0o600
    assert credentials.parent.stat().st_mode & 0o777 == 0o700
    assert "HF_TOKEN" not in credentials.read_text(encoding="utf-8")
    assert "EXA_API_KEY" not in credentials.read_text(encoding="utf-8")
    assert "MODEL_REVISION" not in credentials.read_text(encoding="utf-8")
    assert API_KEY not in completed.stdout + completed.stderr


def test_sync_is_idempotent_for_the_same_key(tmp_path: Path) -> None:
    first, credentials = run_sync(tmp_path)
    original_inode = credentials.stat().st_ino
    second_environment = environment(tmp_path / "second")
    second_environment["HOME"] = str(credentials.parents[2])

    second = subprocess.run(
        [str(SYNC_SCRIPT)],
        env=second_environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert first.returncode == 0
    assert second.returncode == 0
    assert "already synchronized" in second.stdout
    assert credentials.stat().st_ino == original_inode
    assert API_KEY not in second.stdout + second.stderr


def test_sync_refuses_a_different_existing_key_without_replace(
    tmp_path: Path,
) -> None:
    completed, credentials = run_sync(tmp_path)
    original = "ALGOHINT_GEMMA_API_KEY=existing-different-key\n"
    credentials.write_text(original, encoding="utf-8")
    credentials.chmod(0o600)
    second_environment = environment(tmp_path / "second")
    second_environment["HOME"] = str(credentials.parents[2])

    refused = subprocess.run(
        [str(SYNC_SCRIPT)],
        env=second_environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert refused.returncode == 2
    assert credentials.read_text(encoding="utf-8") == original
    assert "rerun with --replace" in refused.stderr
    assert API_KEY not in refused.stdout + refused.stderr


def test_sync_replace_preserves_previous_credentials_in_garbage(
    tmp_path: Path,
) -> None:
    completed, credentials = run_sync(tmp_path)
    original = "ALGOHINT_GEMMA_API_KEY=existing-different-key\n"
    credentials.write_text(original, encoding="utf-8")
    credentials.chmod(0o600)
    second_environment = environment(tmp_path / "second")
    second_environment["HOME"] = str(credentials.parents[2])

    replaced = subprocess.run(
        [str(SYNC_SCRIPT), "--replace"],
        env=second_environment,
        check=False,
        capture_output=True,
        text=True,
    )

    backups = tuple((credentials.parent / "_GARBAGE").iterdir())
    assert completed.returncode == 0
    assert replaced.returncode == 0
    assert credentials.read_text(encoding="utf-8") == (
        f"ALGOHINT_GEMMA_API_KEY={API_KEY}\n"
    )
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original
    assert backups[0].stat().st_mode & 0o777 == 0o600
    assert API_KEY not in replaced.stdout + replaced.stderr


def test_sync_rejects_remote_permission_failure_without_local_file(
    tmp_path: Path,
) -> None:
    resolved_environment = environment(tmp_path)
    remote_path = remote_credentials(
        Path(resolved_environment["FAKE_REMOTE_HOME"]),
        mode=0o644,
    )

    completed = subprocess.run(
        [str(SYNC_SCRIPT)],
        env=resolved_environment,
        check=False,
        capture_output=True,
        text=True,
    )

    local_path = (
        Path(resolved_environment["HOME"])
        / ".config"
        / "algohint"
        / "gemma-remote-credentials"
    )
    assert remote_path.stat().st_mode & 0o777 == 0o644
    assert completed.returncode == 2
    assert "group or world permissions" in completed.stderr
    assert not local_path.exists()
    assert API_KEY not in completed.stdout + completed.stderr


def test_sync_rejects_an_empty_remote_api_key(tmp_path: Path) -> None:
    resolved_environment = environment(tmp_path)
    remote_path = (
        Path(resolved_environment["FAKE_REMOTE_HOME"])
        / ".config"
        / "algohint-gemma-server"
        / "credentials"
    )
    remote_path.write_text("ALGOHINT_GEMMA_API_KEY=''\n", encoding="utf-8")
    remote_path.chmod(0o600)

    completed = subprocess.run(
        [str(SYNC_SCRIPT)],
        env=resolved_environment,
        check=False,
        capture_output=True,
        text=True,
    )

    local_path = (
        Path(resolved_environment["HOME"])
        / ".config"
        / "algohint"
        / "gemma-remote-credentials"
    )
    assert completed.returncode == 2
    assert "missing or invalid" in completed.stderr
    assert not local_path.exists()


def test_sync_rejects_a_local_credentials_symlink_before_ssh(
    tmp_path: Path,
) -> None:
    resolved_environment = environment(tmp_path)
    credentials = (
        Path(resolved_environment["HOME"])
        / ".config"
        / "algohint"
        / "gemma-remote-credentials"
    )
    credentials.parent.mkdir(parents=True, exist_ok=True)
    credentials.parent.chmod(0o700)
    symlink_target = tmp_path / "outside-credentials"
    symlink_target.write_text("must-not-change\n", encoding="utf-8")
    credentials.symlink_to(symlink_target)
    marker = tmp_path / "ssh-called"
    write_executable(
        tmp_path / "bin" / "ssh",
        f"touch {marker}\n",
    )

    completed = subprocess.run(
        [str(SYNC_SCRIPT)],
        env=resolved_environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "regular non-symlink file" in completed.stderr
    assert symlink_target.read_text(encoding="utf-8") == "must-not-change\n"
    assert not marker.exists()


def test_sync_rejects_tampered_multiline_response(tmp_path: Path) -> None:
    completed, credentials = run_sync(
        tmp_path,
        ssh_body="printf 'unexpected\\nZmFrZQ==\\n'\n",
    )

    assert completed.returncode == 2
    assert "not one valid Base64 value" in completed.stderr
    assert not credentials.exists()


def test_sync_rejects_removed_target_environment_before_ssh(tmp_path: Path) -> None:
    resolved_environment = environment(tmp_path)
    resolved_environment["ALGOHINT_SSH_TARGET"] = ""
    marker = tmp_path / "ssh-called"
    write_executable(
        tmp_path / "bin" / "ssh",
        f"touch {marker}\n",
    )

    completed = subprocess.run(
        [str(SYNC_SCRIPT)],
        env=resolved_environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "is no longer supported" in completed.stderr
    assert "unset ALGOHINT_SSH_TARGET" in completed.stderr
    assert not marker.exists()
