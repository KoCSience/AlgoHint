"""Shell control tests use fake tmux/curl binaries and never start a model."""

import os
import subprocess
from pathlib import Path

SERVICE_ROOT = Path(__file__).parents[1]
CONTROL_SCRIPT = SERVICE_ROOT / "scripts" / "server-control.sh"
RUN_SCRIPT = SERVICE_ROOT / "scripts" / "run-server.sh"


def _fake_tools(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "tmux-calls"
    tmux = fake_bin / "tmux"
    tmux.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >>"$FAKE_TMUX_CALLS"
if [[ "${1:-}" == "has-session" && "${FAKE_TMUX_RUNNING:-0}" != "1" ]]; then
    exit 1
fi
""",
        encoding="utf-8",
    )
    tmux.chmod(0o755)
    curl = fake_bin / "curl"
    curl.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    curl.chmod(0o755)
    return fake_bin, calls


def _environment(tmp_path: Path, fake_bin: Path, calls: Path) -> dict[str, str]:
    app_root = tmp_path / "gemma"
    uvicorn = app_root / ".venv" / "bin" / "uvicorn"
    uvicorn.parent.mkdir(parents=True)
    uvicorn.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    uvicorn.chmod(0o755)
    credentials = tmp_path / "gemma-credentials"
    credentials.write_text(
        "ALGOHINT_GEMMA_API_KEY='test-only-api-key-that-is-long-enough'\n",
        encoding="utf-8",
    )
    return {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_TMUX_CALLS": str(calls),
        "ALGOHINT_GEMMA_APP_ROOT": str(app_root),
        "ALGOHINT_GEMMA_CODE_ROOT": str(SERVICE_ROOT),
        "ALGOHINT_GEMMA_STATE_DIR": str(app_root / "state"),
        "ALGOHINT_GEMMA_CREDENTIALS": str(credentials),
        "ALGOHINT_GEMMA_LOG_MAX_BYTES": "1024",
        "ALGOHINT_GEMMA_LOG_GENERATIONS": "2",
    }


def test_shell_scripts_parse() -> None:
    result = subprocess.run(
        ["bash", "-n", str(RUN_SCRIPT), str(CONTROL_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_start_creates_monitor_log_pane_and_server_window(tmp_path: Path) -> None:
    fake_bin, calls = _fake_tools(tmp_path)
    environment = _environment(tmp_path, fake_bin, calls)
    log_path = Path(environment["ALGOHINT_GEMMA_STATE_DIR"]) / "server.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("x" * 1_100, encoding="utf-8")

    result = subprocess.run(
        [str(CONTROL_SCRIPT), "start"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "new-session -d -s algohint-gemma -n monitor" in recorded
    assert "split-window -v -t algohint-gemma:monitor" in recorded
    assert "new-window -d -t algohint-gemma -n server" in recorded
    assert "pipe-pane -o -t algohint-gemma:server.0" in recorded
    assert "select-window -t algohint-gemma:monitor" in recorded
    assert (log_path.parent / "server.log.1").stat().st_size == 1_100
    assert log_path.stat().st_size == 0


def test_stop_refuses_unvalidated_pid_and_still_closes_monitor(tmp_path: Path) -> None:
    fake_bin, calls = _fake_tools(tmp_path)
    environment = _environment(tmp_path, fake_bin, calls)
    environment["FAKE_TMUX_RUNNING"] = "1"
    state_dir = Path(environment["ALGOHINT_GEMMA_STATE_DIR"])
    state_dir.mkdir(parents=True)
    (state_dir / "server.pid").write_text(str(os.getpid()), encoding="utf-8")

    result = subprocess.run(
        [str(CONTROL_SCRIPT), "stop"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Refusing to signal unvalidated PID" in result.stderr
    assert "kill-session -t algohint-gemma" in calls.read_text(encoding="utf-8")
