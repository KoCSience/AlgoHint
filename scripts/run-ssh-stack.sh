#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
algohint_runner="${ALGOHINT_RUN_ALGOHINT_SCRIPT:-$project_root/scripts/run-algohint.sh}"
remote_wait_helper="$project_root/scripts/wait-gemma-ready-remote.sh"
release_manifest="$project_root/config/gemma-server-release.conf"
remote_installer="${ALGOHINT_INSTALL_GEMMA_SERVER_SCRIPT:-$project_root/scripts/install-gemma-server-ssh.sh}"
# shellcheck source=scripts/lib/gemma-ssh-target.sh
. "$project_root/scripts/lib/gemma-ssh-target.sh"
# shellcheck source=scripts/lib/gemma-stack-health.sh
. "$project_root/scripts/lib/gemma-stack-health.sh"
# shellcheck source=scripts/lib/gemma-ssh-runtime.sh
. "$project_root/scripts/lib/gemma-ssh-runtime.sh"
local_port="${ALGOHINT_SSH_LOCAL_PORT:-18000}"
remote_port="${ALGOHINT_SSH_REMOTE_PORT:-18080}"
startup_timeout="${ALGOHINT_SSH_STARTUP_TIMEOUT:-900}"
monitor_interval="${ALGOHINT_GEMMA_MONITOR_INTERVAL_SECONDS:-5}"
health_failure_threshold=3
keep_remote=false
install_remote=false
started_remote=false
tunnel_pid=""
algohint_pid=""
monitor_pid=""

while (($# > 0)); do
    case "$1" in
        --keep-remote) keep_remote=true ;;
        --install-remote) install_remote=true ;;
        --)
            shift
            break
            ;;
        *) break ;;
    esac
    shift
done
app_arguments=("$@")
ssh_target="$(algohint_read_gemma_ssh_target)"

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
if [[ ! "$monitor_interval" =~ ^[1-9][0-9]*$ ]] || ((monitor_interval > 60)); then
    echo "ALGOHINT_GEMMA_MONITOR_INTERVAL_SECONDS must be between 1 and 60 seconds." >&2
    exit 2
fi
if ! command -v ssh >/dev/null 2>&1; then
    echo "ssh is required for the remote Gemma stack." >&2
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
if [[ ! -r "$remote_wait_helper" ]]; then
    echo "Remote Gemma readiness helper is missing: $remote_wait_helper" >&2
    exit 2
fi
if [[ ! -r "$release_manifest" ]]; then
    echo "Gemma Server release manifest is missing: $release_manifest" >&2
    exit 2
fi
expected_remote_commit="$(
    sed -n "s/^ALGOHINT_GEMMA_SERVER_COMMIT='\([0-9a-f]\{40\}\)'$/\1/p" \
        "$release_manifest"
)"
if [[ ! "$expected_remote_commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Gemma Server release manifest has no valid full commit SHA." >&2
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
for remote_path_name in remote_app_root remote_control; do
    remote_path="${!remote_path_name}"
    if [[ -z "$remote_path" || "$remote_path" == *$'\n'* ]]; then
        echo "$remote_path_name must be one non-empty remote path without newlines." >&2
        exit 2
    fi
done
quoted_control="$(quote_remote "$remote_control")"
health_url="http://127.0.0.1:$local_port/healthz"
export ALGOHINT_GEMMA_BACKEND="transformers_http"
export ALGOHINT_GEMMA_DEPLOYMENT="remote"
export ALGOHINT_GEMMA_BASE_URL="http://127.0.0.1:$local_port/v1"
export ALGOHINT_MANAGED_GEMMA_DEPLOYMENT="$ALGOHINT_GEMMA_DEPLOYMENT"
export ALGOHINT_MANAGED_GEMMA_BASE_URL="$ALGOHINT_GEMMA_BASE_URL"

remote_control_command() {
    local action="$1"
    ssh -T "$ssh_target" \
        "ALGOHINT_GEMMA_INSTALL_ROOT=$(quote_remote "$remote_app_root") $quoted_control $(quote_remote "$action")"
}

refresh_remote_runtime_state() {
    if ! algohint_refresh_remote_runtime_state "$ssh_target" "$remote_app_root"; then
        echo "Could not inspect the remote Gemma release and runtime state." >&2
        exit 2
    fi
    if [[ "$ALGOHINT_REMOTE_NATIVE_STATE" == "unknown" ||
        "$ALGOHINT_REMOTE_DOCKER_STATE" == "unknown" ]]; then
        echo "A remote Gemma controller returned an ambiguous state." >&2
        exit 2
    fi
}

ensure_remote_release() {
    refresh_remote_runtime_state
    if [[ "$ALGOHINT_REMOTE_RELEASE" == "$expected_remote_commit" ]]; then
        return
    fi
    if [[ "$ALGOHINT_REMOTE_NATIVE_STATE" == "running" ||
        "$ALGOHINT_REMOTE_DOCKER_STATE" == "running" ]]; then
        algohint_print_remote_stop_guidance
        exit 2
    fi
    if [[ "$install_remote" != true ]]; then
        echo "Remote Gemma release does not match the pinned release." >&2
        echo "Expected commit: $expected_remote_commit" >&2
        echo "Current commit: $ALGOHINT_REMOTE_RELEASE" >&2
        echo "Retry with --install-remote after reviewing the fixed release." >&2
        exit 2
    fi
    if [[ ! -x "$remote_installer" ]]; then
        echo "Pinned Gemma Server installer is missing: $remote_installer" >&2
        exit 2
    fi
    echo "Installing pinned Gemma Server release on $ssh_target: $expected_remote_commit"
    "$remote_installer"
    refresh_remote_runtime_state
    if [[ "$ALGOHINT_REMOTE_RELEASE" != "$expected_remote_commit" ]]; then
        echo "Pinned Gemma Server installation did not activate the expected release." >&2
        echo "Expected commit: $expected_remote_commit" >&2
        echo "Current commit: $ALGOHINT_REMOTE_RELEASE" >&2
        exit 2
    fi
}

wait_for_remote_server() {
    local remote_command
    remote_command="bash -s -- $quoted_control $(quote_remote "$startup_timeout") 10 15"
    ssh -T "$ssh_target" "$remote_command" <"$remote_wait_helper"
}

# Refuse old releases and cross-mode ownership before starting a model. This
# avoids spending model-load time only to discover that the probe API is absent.
ensure_remote_release
if [[ "$ALGOHINT_REMOTE_DOCKER_STATE" == "running" ]]; then
    algohint_print_remote_stop_guidance
    exit 2
fi

# Distinguish an incomplete remote installation from a controller or model
# failure before starting any process that this launcher would then own.
if ssh -T "$ssh_target" "test -x $quoted_control"; then
    :
else
    control_check_exit=$?
    if ((control_check_exit == 255)); then
        echo "Could not verify the remote Gemma Server control script over SSH." >&2
        echo "Target: $ssh_target" >&2
    else
        echo "Remote Gemma Server control script is missing or not executable." >&2
        echo "Target: $ssh_target" >&2
        echo "Expected path: $remote_control" >&2
        echo "Complete the standalone Gemma Server setup before using this launcher:" >&2
        echo "https://github.com/KoCSience/AlgoHint-Gemma-Server" >&2
        echo "If it is installed elsewhere, set ALGOHINT_SSH_REMOTE_APP_ROOT." >&2
    fi
    exit 2
fi

wait_for_tunnel() {
    local attempt
    for ((attempt = 0; attempt < startup_timeout; attempt++)); do
        if [[ -n "$tunnel_pid" ]] && ! kill -0 "$tunnel_pid" 2>/dev/null; then
            echo "SSH tunnel exited before Gemma Server became ready." >&2
            return 1
        fi
        if algohint_gemma_is_ready "$health_url"; then
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
    if [[ -n "$tunnel_pid" ]]; then
        if kill -0 "$tunnel_pid" 2>/dev/null; then
            kill -TERM "$tunnel_pid" 2>/dev/null || true
        fi
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

# Uvicorn does not listen until model loading completes. Waiting on the GPU
# host first prevents each local health probe from surfacing as an SSH channel
# "Connection refused" error while startup is still progressing normally.
wait_for_remote_server
ssh -N -T \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -L "127.0.0.1:$local_port:127.0.0.1:$remote_port" \
    "$ssh_target" &
tunnel_pid=$!
wait_for_tunnel
algohint_verify_gemma_contract "$algohint_runner" "${app_arguments[@]}"

"$algohint_runner" "${app_arguments[@]}" &
algohint_pid=$!
algohint_monitor_gemma_health \
    "$health_url" \
    "$monitor_interval" \
    "$health_failure_threshold" \
    "Gemma Server or SSH tunnel health was lost after startup." &
monitor_pid=$!
set +e
wait "$algohint_pid"
app_exit=$?
set -e
algohint_pid=""
exit "$app_exit"
