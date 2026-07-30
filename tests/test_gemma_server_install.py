"""Gemma Server bootstrap tests never contact GitHub or install model packages."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_INSTALLER = PROJECT_ROOT / "scripts" / "install-gemma-server-ssh.sh"
REMOTE_BOOTSTRAP = PROJECT_ROOT / "scripts" / "bootstrap-gemma-server-remote.sh"
MANIFEST = PROJECT_ROOT / "config" / "gemma-server-release.conf"
GEMMA_GUIDE = PROJECT_ROOT / "docs" / "gemma-server.md"
DEVELOPMENT_GUIDE = PROJECT_ROOT / "docs" / "development.md"
E2E_GUIDE = PROJECT_ROOT / "docs" / "e2e-debugging.md"
README = PROJECT_ROOT / "README.md"


def write_executable(path: Path, body: str) -> None:
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


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_release_manifest_pins_public_repository_and_full_commit() -> None:
    values: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, raw_value = line.split("=", maxsplit=1)
            values[name] = raw_value.strip("'")

    assert values["ALGOHINT_GEMMA_SERVER_REPOSITORY"] == (
        "https://github.com/KoCSience/AlgoHint-Gemma-Server.git"
    )
    commit = values["ALGOHINT_GEMMA_SERVER_COMMIT"]
    assert len(commit) == 40
    assert all(character in "0123456789abcdef" for character in commit)


def test_algohint_contains_only_consumer_side_gemma_integration() -> None:
    embedded_service = PROJECT_ROOT / "services" / "gemma-transformers-server"
    local_launcher = (PROJECT_ROOT / "scripts" / "run-local-stack.sh").read_text(
        encoding="utf-8"
    )

    assert not embedded_service.exists()
    assert "services/gemma-transformers-server" not in local_launcher
    assert "current/scripts/server-control.sh" in local_launcher


def test_gemma_guide_uses_minimal_credential_sync_and_host_labels() -> None:
    guide = GEMMA_GUIDE.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    related_guides = "\n".join(
        (
            guide,
            DEVELOPMENT_GUIDE.read_text(encoding="utf-8"),
            E2E_GUIDE.read_text(encoding="utf-8"),
            readme,
        )
    )

    assert "scripts/sync-gemma-credentials-ssh.sh" in guide
    assert "scripts/check-gemma-ssh.sh" in guide
    assert "実行場所: AlgoHint host" in guide
    assert "実行場所: GPU host" in guide
    assert "SSH connection OK: AlgoHint host -> GPU host" in guide
    assert "$HOME/.config/algohint/gemma-ssh-target" in readme
    assert (
        "${XDG_CONFIG_HOME:-$HOME/.config}/algohint-gemma-server/credentials"
        in readme
    )
    assert "$HOME/.config/algohint/gemma-remote-credentials" in readme
    assert "Gemma client credentials are already synchronized" in readme
    assert "ALGOHINT_SSH_TARGET='" not in related_guides
    assert 'export ALGOHINT_SSH_TARGET=' not in related_guides
    assert 'ssh -T "$ALGOHINT_SSH_TARGET"' not in related_guides
    assert "scp " not in guide


def test_local_installer_sends_reviewed_bootstrap_and_pinned_values(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    ssh_log = tmp_path / "ssh.log"
    stdin_copy = tmp_path / "bootstrap.copy"
    local_home = tmp_path / "local-home"
    local_home.mkdir()
    write_ssh_target(local_home)
    write_executable(
        fake_bin / "ssh",
        'printf "%s\\n" "$*" >> "$TEST_SSH_LOG"\n'
        'if [[ "$*" != *"bash -s --"* ]]; then\n'
        '  printf "/remote/tester\\n"\n'
        "else\n"
        '  cp /dev/stdin "$TEST_STDIN_COPY"\n'
        "fi\n",
    )
    environment = os.environ.copy()
    environment.pop("ALGOHINT_SSH_TARGET", None)
    environment.update(
        {
            "HOME": str(local_home),
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "TEST_SSH_LOG": str(ssh_log),
            "TEST_STDIN_COPY": str(stdin_copy),
        }
    )

    completed = subprocess.run(
        [str(LOCAL_INSTALLER)],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    calls = ssh_log.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    pinned_commit = next(
        line.split("=", maxsplit=1)[1].strip("'")
        for line in manifest.splitlines()
        if line.startswith("ALGOHINT_GEMMA_SERVER_COMMIT=")
    )
    assert "gpu-test-host" in calls
    assert "https://github.com/KoCSience/AlgoHint-Gemma-Server.git" in calls
    assert pinned_commit in calls
    assert "/remote/tester/programs/algohint-gemma-server" in calls
    assert stdin_copy.read_bytes() == REMOTE_BOOTSTRAP.read_bytes()
    assert "release installed" in completed.stdout


def test_remote_bootstrap_uses_exact_commit_in_temporary_worktree(
    tmp_path: Path,
) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q")
    git(origin, "config", "user.name", "Test")
    git(origin, "config", "user.email", "test@example.invalid")
    deploy_log = tmp_path / "deploy.log"
    write_executable(
        origin / "scripts" / "deploy-release.sh",
        'printf "%s root=%s\\n" "$1" "$ALGOHINT_GEMMA_INSTALL_ROOT" '
        '>> "$TEST_DEPLOY_LOG"\n',
    )
    git(origin, "add", "scripts/deploy-release.sh")
    git(origin, "commit", "-q", "-m", "test release")
    commit = git(origin, "rev-parse", "HEAD")
    install_root = tmp_path / "install"
    source_cache = tmp_path / "cache" / "source.git"
    environment = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "TEST_DEPLOY_LOG": str(deploy_log),
    }

    completed = subprocess.run(
        [
            str(REMOTE_BOOTSTRAP),
            str(origin),
            commit,
            str(install_root),
            str(source_cache),
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert deploy_log.read_text(encoding="utf-8") == (
        f"{commit} root={install_root}\n"
    )
    assert source_cache.is_dir()
    assert git(source_cache, "rev-parse", commit) == commit


def test_remote_bootstrap_refuses_cache_with_different_origin(tmp_path: Path) -> None:
    cache = tmp_path / "cache.git"
    cache.mkdir()
    git(cache, "init", "--bare", "-q")
    git(cache, "remote", "add", "origin", "different-origin")

    completed = subprocess.run(
        [
            str(REMOTE_BOOTSTRAP),
            "expected-origin",
            "a" * 40,
            str(tmp_path / "install"),
            str(cache),
        ],
        env={**os.environ, "HOME": str(tmp_path / "home")},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "origin does not match" in completed.stderr


def test_remote_bootstrap_resolves_user_uv_outside_noninteractive_path(
    tmp_path: Path,
) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q")
    git(origin, "config", "user.name", "Test")
    git(origin, "config", "user.email", "test@example.invalid")
    deploy_log = tmp_path / "deploy.log"
    write_executable(
        origin / "scripts" / "deploy-release.sh",
        'printf "uv=%s\\n" "$(command -v uv)" > "$TEST_DEPLOY_LOG"\n',
    )
    git(origin, "add", "scripts/deploy-release.sh")
    git(origin, "commit", "-q", "-m", "test user uv")
    commit = git(origin, "rev-parse", "HEAD")
    remote_home = tmp_path / "remote-home"
    user_uv = remote_home / ".local" / "bin" / "uv"
    write_executable(user_uv, "exit 0\n")

    completed = subprocess.run(
        [
            str(REMOTE_BOOTSTRAP),
            str(origin),
            commit,
            str(tmp_path / "install"),
            str(tmp_path / "cache" / "source.git"),
        ],
        env={
            **os.environ,
            "HOME": str(remote_home),
            "PATH": "/usr/bin:/bin",
            "TEST_DEPLOY_LOG": str(deploy_log),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert deploy_log.read_text(encoding="utf-8") == f"uv={user_uv}\n"
