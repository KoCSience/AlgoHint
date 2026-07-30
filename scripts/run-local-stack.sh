#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=scripts/lib/gemma-stack-health.sh
. "$project_root/scripts/lib/gemma-stack-health.sh"
gemma_install_root="${ALGOHINT_GEMMA_INSTALL_ROOT:-$HOME/programs/algohint-gemma-server}"
gemma_control="${ALGOHINT_LOCAL_GEMMA_CONTROL:-$gemma_install_root/current/scripts/server-control.sh}"
algohint_runner="${ALGOHINT_RUN_ALGOHINT_SCRIPT:-$project_root/scripts/run-algohint.sh}"
startup_timeout="${ALGOHINT_GEMMA_STARTUP_TIMEOUT:-300}"
monitor_interval="${ALGOHINT_GEMMA_MONITOR_INTERVAL_SECONDS:-5}"
health_failure_threshold=3
gemma_port=18080
keep_gemma=false
started_gemma=false
algohint_pid=""
monitor_pid=""

if [[ "${1:-}" == "--keep-gemma" ]]; then
    keep_gemma=true
    shift
fi
if [[ ! "$startup_timeout" =~ ^[1-9][0-9]*$ ]] || ((startup_timeout > 3600)); then
    echo "ALGOHINT_GEMMA_STARTUP_TIMEOUT must be between 1 and 3600 seconds." >&2
    exit 2
fi
if [[ ! "$monitor_interval" =~ ^[1-9][0-9]*$ ]] || ((monitor_interval > 60)); then
    echo "ALGOHINT_GEMMA_MONITOR_INTERVAL_SECONDS must be between 1 and 60 seconds." >&2
    exit 2
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required for Gemma Server health checks." >&2
    exit 2
fi
if [[ ! -x "$algohint_runner" ]]; then
    echo "AlgoHint launcher is missing or not executable: $algohint_runner" >&2
    exit 2
fi
if [[ ! -x "$gemma_control" ]]; then
    echo "Standalone Gemma Server control script is missing: $gemma_control" >&2
    echo "Install the pinned release before using the local stack." >&2
    echo "See: $project_root/docs/gemma-server.md" >&2
    exit 2
fi

health_url="http://127.0.0.1:$gemma_port/healthz"
export ALGOHINT_GEMMA_BACKEND="transformers_http"
export ALGOHINT_GEMMA_DEPLOYMENT="local"
export ALGOHINT_GEMMA_BASE_URL="http://127.0.0.1:$gemma_port/v1"
export ALGOHINT_MANAGED_GEMMA_DEPLOYMENT="$ALGOHINT_GEMMA_DEPLOYMENT"
export ALGOHINT_MANAGED_GEMMA_BASE_URL="$ALGOHINT_GEMMA_BASE_URL"

wait_for_gemma() {
    local attempt
    for ((attempt = 0; attempt < startup_timeout; attempt++)); do
        if algohint_gemma_is_ready "$health_url"; then
            return
        fi
        sleep 1
    done
    echo "Gemma Server did not become ready within ${startup_timeout}s." >&2
    "$gemma_control" status >&2 || true
    echo "Inspect logs with: $gemma_control logs" >&2
    return 1
}

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    if [[ -n "$monitor_pid" ]]; then
        if kill -0 "$monitor_pid" 2>/dev/null; then
            kill -TERM "$monitor_pid" 2>/dev/null || true
        fi
        wait "$monitor_pid" 2>/dev/null || true
    fi
    if [[ -n "$algohint_pid" ]] && kill -0 "$algohint_pid" 2>/dev/null; then
        kill -TERM "$algohint_pid" 2>/dev/null || true
        wait "$algohint_pid" 2>/dev/null || true
    fi
    if [[ "$started_gemma" == true && "$keep_gemma" == false ]]; then
        "$gemma_control" stop || true
    fi
    exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

gemma_status="$("$gemma_control" status 2>&1 || true)"
if grep -q "process: running" <<<"$gemma_status"; then
    echo "Using the Gemma Server that was already running."
else
    "$gemma_control" start
    started_gemma=true
fi
wait_for_gemma
algohint_verify_gemma_contract "$algohint_runner" "$@"

"$algohint_runner" "$@" &
algohint_pid=$!
algohint_monitor_gemma_health \
    "$health_url" \
    "$monitor_interval" \
    "$health_failure_threshold" \
    "Gemma Server health was lost after startup." &
monitor_pid=$!
set +e
wait "$algohint_pid"
app_exit=$?
set -e
algohint_pid=""
exit "$app_exit"
