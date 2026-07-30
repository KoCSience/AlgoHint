#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

# This controller owns only one named tmux session and one validated Uvicorn PID.
# It never searches for or terminates arbitrary Python processes.
session_name="${ALGOHINT_GEMMA_TMUX_SESSION:-algohint-gemma}"
app_root="${ALGOHINT_GEMMA_APP_ROOT:-$HOME/programs/algohint-gemma-server}"
code_root="${ALGOHINT_GEMMA_CODE_ROOT:-$app_root/current}"
state_dir="${ALGOHINT_GEMMA_STATE_DIR:-$app_root/state}"
status_file="${ALGOHINT_GEMMA_STATUS_FILE:-$state_dir/status.json}"
log_file="${ALGOHINT_GEMMA_LOG_FILE:-$state_dir/server.log}"
pid_file="${ALGOHINT_GEMMA_PID_FILE:-$state_dir/server.pid}"
credentials_path="${ALGOHINT_GEMMA_CREDENTIALS:-$HOME/.config/algohint-gemma-server/credentials}"
server_port="${ALGOHINT_GEMMA_PORT:-18080}"
control_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/server-control.sh"
run_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/run-server.sh"
health_url="http://127.0.0.1:$server_port/healthz"

validated_integer() {
    local name="$1"
    local value="$2"
    local minimum="$3"
    local maximum="$4"
    if [[ ! "$value" =~ ^[0-9]+$ ]] || ((value < minimum || value > maximum)); then
        echo "$name must be between $minimum and $maximum" >&2
        exit 2
    fi
}

rotate_log() {
    local max_bytes="${ALGOHINT_GEMMA_LOG_MAX_BYTES:-10485760}"
    local generations="${ALGOHINT_GEMMA_LOG_GENERATIONS:-5}"
    validated_integer "ALGOHINT_GEMMA_LOG_MAX_BYTES" "$max_bytes" 1024 1073741824
    validated_integer "ALGOHINT_GEMMA_LOG_GENERATIONS" "$generations" 1 20
    [[ -f "$log_file" ]] || return
    local size
    size="$(wc -c <"$log_file")"
    ((size >= max_bytes)) || return

    local index
    for ((index = generations; index >= 2; index--)); do
        if [[ -f "$log_file.$((index - 1))" ]]; then
            mv -f "$log_file.$((index - 1))" "$log_file.$index"
        fi
    done
    mv -f "$log_file" "$log_file.1"
}

read_pid() {
    [[ -r "$pid_file" ]] || return 1
    local candidate
    IFS= read -r candidate <"$pid_file"
    [[ "$candidate" =~ ^[1-9][0-9]*$ ]] || return 1
    printf '%s\n' "$candidate"
}

pid_is_server() {
    local candidate="$1"
    [[ -r "/proc/$candidate/cmdline" ]] || return 1
    local command_line
    command_line="$(tr '\0' ' ' <"/proc/$candidate/cmdline")"
    [[ "$command_line" == *uvicorn* ]] &&
        [[ "$command_line" == *algohint_gemma_server.app:create_app* ]]
}

tmux_is_running() {
    command -v tmux >/dev/null 2>&1 &&
        tmux has-session -t "$session_name" 2>/dev/null
}

print_status_file() {
    if [[ ! -r "$status_file" ]]; then
        echo "state-file: missing ($status_file)"
        return
    fi
    python3 - "$status_file" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    status = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    print(f"state-file: invalid ({path})")
else:
    fields = ("state", "updated_at", "pid", "model_id", "revision",
              "request_kind", "elapsed_ms", "exception_type")
    print("state-file:")
    for field in fields:
        if field in status:
            print(f"  {field}: {status[field]}")
PY
}

status_command() {
    local tmux_state="not-running"
    tmux_is_running && tmux_state="running"
    echo "tmux: $tmux_state ($session_name)"

    local server_pid=""
    if server_pid="$(read_pid)" && pid_is_server "$server_pid"; then
        echo "process: running (pid=$server_pid, validated)"
    elif [[ -n "$server_pid" ]]; then
        echo "process: WARNING pid=$server_pid is absent or no longer the Gemma Uvicorn process"
    else
        echo "process: not-running"
    fi

    print_status_file
    if command -v curl >/dev/null 2>&1 &&
        health="$(curl --silent --show-error --fail --max-time 2 "$health_url" 2>/dev/null)"; then
        echo "healthz: $health"
    else
        echo "healthz: unavailable ($health_url)"
    fi

    if [[ "$tmux_state" == "running" && -z "$server_pid" ]]; then
        echo "WARNING: monitor is running without a validated server process"
    elif [[ "$tmux_state" == "not-running" && -n "$server_pid" ]] &&
        pid_is_server "$server_pid"; then
        echo "WARNING: validated server process exists outside the expected tmux session"
    fi
}

monitor_command() {
    while true; do
        clear 2>/dev/null || true
        echo "AlgoHint Gemma runtime monitor"
        date --iso-8601=seconds
        echo
        status_command
        echo
        if command -v nvidia-smi >/dev/null 2>&1; then
            nvidia-smi \
                --query-gpu=index,name,memory.used,memory.total,utilization.gpu \
                --format=csv,noheader,nounits 2>/dev/null ||
                echo "GPU: nvidia-smi is temporarily unavailable"
        else
            echo "GPU: nvidia-smi is not installed"
        fi
        sleep 2
    done
}

logs_command() {
    local follow="${1:-}"
    install -d -m 700 "$state_dir"
    touch "$log_file"
    chmod 600 "$log_file"
    if [[ "$follow" == "--follow" ]]; then
        exec tail -n 100 -F "$log_file"
    fi
    tail -n 100 "$log_file"
}

start_command() {
    if ! command -v tmux >/dev/null 2>&1; then
        echo "tmux is required. Install it before starting Gemma Server." >&2
        exit 2
    fi
    if tmux_is_running; then
        echo "Gemma tmux session is already running: $session_name"
        status_command
        return
    fi
    if [[ ! -x "$run_script" ]]; then
        echo "Gemma run script is not executable: $run_script" >&2
        exit 2
    fi
    if [[ ! -r "$credentials_path" ]]; then
        echo "Gemma credentials are missing or unreadable: $credentials_path" >&2
        echo "Create the documented 0600 credentials file before starting." >&2
        exit 2
    fi
    if [[ ! -x "$app_root/.venv/bin/uvicorn" ]]; then
        echo "Gemma dependencies are not installed at $app_root/.venv." >&2
        echo "Run the documented frozen uv sync before starting." >&2
        exit 2
    fi

    install -d -m 700 "$state_dir"
    rotate_log
    touch "$log_file"
    chmod 600 "$log_file"

    local monitor_shell logs_shell server_shell pipe_shell
    printf -v monitor_shell '%q ' "$control_script" "__monitor"
    printf -v logs_shell '%q ' "$control_script" "logs" "--follow"
    printf -v server_shell \
        'sleep 1; exec env ALGOHINT_GEMMA_APP_ROOT=%q ALGOHINT_GEMMA_CODE_ROOT=%q ALGOHINT_GEMMA_STATE_DIR=%q ALGOHINT_GEMMA_STATUS_FILE=%q ALGOHINT_GEMMA_LOG_FILE=%q ALGOHINT_GEMMA_PID_FILE=%q ALGOHINT_GEMMA_CREDENTIALS=%q ALGOHINT_GEMMA_PORT=%q %q' \
        "$app_root" "$code_root" "$state_dir" "$status_file" "$log_file" \
        "$pid_file" "$credentials_path" "$server_port" "$run_script"
    printf -v pipe_shell 'exec cat >> %q' "$log_file"

    tmux new-session -d -s "$session_name" -n monitor "$monitor_shell"
    tmux split-window -v -t "$session_name:monitor" "$logs_shell"
    tmux select-layout -t "$session_name:monitor" even-vertical >/dev/null
    tmux new-window -d -t "$session_name" -n server "$server_shell"
    tmux set-option -w -t "$session_name:server" remain-on-exit on >/dev/null
    tmux pipe-pane -o -t "$session_name:server.0" "$pipe_shell"
    tmux select-window -t "$session_name:monitor"
    echo "Gemma Server tmux monitor started: $session_name"
    echo "Attach with: $control_script attach"
}

stop_command() {
    local server_pid=""
    if server_pid="$(read_pid)" && pid_is_server "$server_pid"; then
        kill -TERM "$server_pid"
        local attempt
        for ((attempt = 0; attempt < 40; attempt++)); do
            kill -0 "$server_pid" 2>/dev/null || break
            sleep 0.25
        done
        if kill -0 "$server_pid" 2>/dev/null && pid_is_server "$server_pid"; then
            echo "Gemma Server did not stop within 10 seconds; terminating validated PID." >&2
            kill -KILL "$server_pid"
        fi
    elif [[ -n "$server_pid" ]]; then
        echo "Refusing to signal unvalidated PID from $pid_file: $server_pid" >&2
    fi

    if tmux_is_running; then
        tmux kill-session -t "$session_name"
    fi
    echo "Gemma Server stop completed."
}

attach_command() {
    if ! tmux_is_running; then
        echo "Gemma tmux session is not running: $session_name" >&2
        exit 1
    fi
    tmux select-window -t "$session_name:monitor"
    exec tmux attach-session -t "$session_name"
}

usage() {
    echo "Usage: $0 start|stop|status|attach|logs"
}

case "${1:-}" in
    start) start_command ;;
    stop) stop_command ;;
    status) status_command ;;
    attach) attach_command ;;
    logs) logs_command "${2:-}" ;;
    __monitor) monitor_command ;;
    __server) exec "$run_script" ;;
    *)
        usage >&2
        exit 2
        ;;
esac
