#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
algohint_runner="${ALGOHINT_RUN_ALGOHINT_SCRIPT:-$project_root/scripts/run-algohint.sh}"
ssh_target="${ALGOHINT_SSH_TARGET:-}"
local_port="${ALGOHINT_SSH_LOCAL_PORT:-18000}"
remote_port="${ALGOHINT_SSH_REMOTE_PORT:-18080}"
startup_timeout="${ALGOHINT_SSH_STARTUP_TIMEOUT:-300}"
keep_remote=false
started_remote=false
tunnel_pid=""
algohint_pid=""

if [[ "${1:-}" == "--keep-remote" ]]; then
    keep_remote=true
    shift
fi
if [[ -z "$ssh_target" ]]; then
    echo "ALGOHINT_SSH_TARGET is required (for example: gpu-learning-host)." >&2
    exit 2
fi
if [[ "$ssh_target" == -* || "$ssh_target" == *$'\n'* ]]; then
    echo "ALGOHINT_SSH_TARGET must be one SSH host or configured alias." >&2
    exit 2
fi
for port_name in local_port remote_port; do
    port_value="${!port_name}"
    if [[ ! "$port_value" =~ ^[1-9][0-9]*$ ]] || ((port_value > 65535)); then
        echo "$port_name must be between 1 and 65535." >&2
        exit 2
    fi
done
if [[ ! "$startup_timeout" =~ ^[1-9][0-9]*$ ]] || ((startup_timeout > 3600)); then
    echo "ALGOHINT_SSH_STARTUP_TIMEOUT must be between 1 and 3600 seconds." >&2
    exit 2
fi
if ! command -v ssh >/dev/null 2>&1; then
    echo "ssh is required for the remote Gemma stack." >&2
    exit 2
fi
if [[ ! -x "$algohint_runner" ]]; then
    echo "AlgoHint launcher is missing or not executable: $algohint_runner" >&2
    exit 2
fi

quote_remote() {
    local value="${1//\'/\'\\\'\'}"
    printf "'%s'" "$value"
}

if [[ -n "${ALGOHINT_SSH_REMOTE_APP_ROOT:-}" ]]; then
    remote_app_root="$ALGOHINT_SSH_REMOTE_APP_ROOT"
else
    remote_home="$(ssh -T "$ssh_target" 'printf "%s\n" "$HOME"')"
    if [[ -z "$remote_home" || "$remote_home" == *$'\n'* ]]; then
        echo "Could not resolve a safe remote home directory." >&2
        exit 2
    fi
    remote_app_root="$remote_home/programs/algohint-gemma-server"
fi
remote_control="${ALGOHINT_SSH_REMOTE_CONTROL:-$remote_app_root/current/scripts/server-control.sh}"
remote_code_root="${ALGOHINT_SSH_REMOTE_CODE_ROOT:-$remote_app_root/current}"
quoted_control="$(quote_remote "$remote_control")"

remote_control_command() {
    local action="$1"
    ssh -T "$ssh_target" \
        "ALGOHINT_GEMMA_APP_ROOT=$(quote_remote "$remote_app_root") ALGOHINT_GEMMA_CODE_ROOT=$(quote_remote "$remote_code_root") $quoted_control $(quote_remote "$action")"
}

wait_for_tunnel() {
    local health_url="http://127.0.0.1:$local_port/healthz"
    local attempt
    for ((attempt = 0; attempt < startup_timeout; attempt++)); do
        if [[ -n "$tunnel_pid" ]] && ! kill -0 "$tunnel_pid" 2>/dev/null; then
            echo "SSH tunnel exited before Gemma Server became ready." >&2
            return 1
        fi
        if command -v curl >/dev/null 2>&1 &&
            curl --silent --fail --max-time 2 "$health_url" 2>/dev/null |
                grep -Eq '"ready"[[:space:]]*:[[:space:]]*true'; then
            return
        fi
        sleep 1
    done
    echo "Remote Gemma Server did not become ready within ${startup_timeout}s." >&2
    remote_control_command status >&2 || true
    return 1
}

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    if [[ -n "$algohint_pid" ]] && kill -0 "$algohint_pid" 2>/dev/null; then
        kill -TERM "$algohint_pid" 2>/dev/null || true
        wait "$algohint_pid" 2>/dev/null || true
    fi
    if [[ -n "$tunnel_pid" ]] && kill -0 "$tunnel_pid" 2>/dev/null; then
        kill -TERM "$tunnel_pid" 2>/dev/null || true
        wait "$tunnel_pid" 2>/dev/null || true
    fi
    if [[ "$started_remote" == true && "$keep_remote" == false ]]; then
        remote_control_command stop || true
    fi
    exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

remote_status="$(remote_control_command status 2>&1 || true)"
if grep -q "process: running" <<<"$remote_status"; then
    echo "Using the Gemma Server that was already running on $ssh_target."
else
    remote_control_command start
    started_remote=true
fi

ssh -N -T \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -L "127.0.0.1:$local_port:127.0.0.1:$remote_port" \
    "$ssh_target" &
tunnel_pid=$!
wait_for_tunnel

export ALGOHINT_GEMMA_BACKEND="${ALGOHINT_GEMMA_BACKEND:-transformers_http}"
export ALGOHINT_GEMMA_DEPLOYMENT="${ALGOHINT_GEMMA_DEPLOYMENT:-remote}"
export ALGOHINT_GEMMA_BASE_URL="${ALGOHINT_GEMMA_BASE_URL:-http://127.0.0.1:$local_port/v1}"

"$algohint_runner" "$@" &
algohint_pid=$!
set +e
wait "$algohint_pid"
app_exit=$?
set -e
algohint_pid=""
exit "$app_exit"
