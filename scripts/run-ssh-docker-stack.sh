#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
compose_file="$project_root/compose.ssh.yaml"
# shellcheck source=scripts/lib/gemma-ssh-target.sh
. "$project_root/scripts/lib/gemma-ssh-target.sh"
# shellcheck source=scripts/lib/gemma-stack-health.sh
. "$project_root/scripts/lib/gemma-stack-health.sh"

credentials_path="${ALGOHINT_CREDENTIALS:-$HOME/.config/algohint/gemma-remote-credentials}"
local_port="${ALGOHINT_SSH_LOCAL_PORT:-18000}"
remote_port="${ALGOHINT_SSH_REMOTE_PORT:-18080}"
startup_timeout="${ALGOHINT_SSH_STARTUP_TIMEOUT:-300}"
monitor_interval="${ALGOHINT_GEMMA_MONITOR_INTERVAL_SECONDS:-5}"
health_failure_threshold=3
container_name="algohint-ssh-app"
project_name="algohint-ssh"
keep_remote=false
build_remote=false
build_local=true
started_remote=false
tunnel_pid=""
app_pid=""
monitor_pid=""

while (($# > 0)); do
    case "$1" in
        --keep-remote) keep_remote=true ;;
        --build-remote) build_remote=true ;;
        --no-build-local) build_local=false ;;
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
if [[ "$local_port" != "18000" ]]; then
    echo "The Docker SSH stack currently requires ALGOHINT_SSH_LOCAL_PORT=18000." >&2
    exit 2
fi
if [[ ! "$startup_timeout" =~ ^[1-9][0-9]*$ ]] || ((startup_timeout > 3600)); then
    echo "ALGOHINT_SSH_STARTUP_TIMEOUT must be between 1 and 3600 seconds." >&2
    exit 2
fi
if [[ ! "$monitor_interval" =~ ^[1-9][0-9]*$ ]] || ((monitor_interval > 60)); then
    echo "ALGOHINT_GEMMA_MONITOR_INTERVAL_SECONDS must be between 1 and 60 seconds." >&2
    exit 2
fi
for executable in curl docker ssh; do
    if ! command -v "$executable" >/dev/null 2>&1; then
        echo "$executable is required for the Docker SSH stack." >&2
        exit 2
    fi
done
docker compose version >/dev/null

validate_credentials() {
    local credentials_mode
    if [[ ! -f "$credentials_path" || -L "$credentials_path" ]]; then
        echo "AlgoHint credentials must be a regular non-symlink file: $credentials_path" >&2
        exit 2
    fi
    if [[ "$(stat -c '%u' "$credentials_path")" != "$(id -u)" ]]; then
        echo "AlgoHint credentials must be owned by the current user." >&2
        exit 2
    fi
    credentials_mode="$(stat -c '%a' "$credentials_path")"
    if (( (8#$credentials_mode & 077) != 0 )); then
        echo "AlgoHint credentials must not grant group or world permissions." >&2
        exit 2
    fi
}

compose() {
    docker compose \
        --env-file /dev/null \
        --project-name "$project_name" \
        --project-directory "$project_root" \
        --file "$compose_file" \
        "$@"
}

quote_remote() {
    local value="${1//\'/\'\\\'\'}"
    printf "'%s'" "$value"
}

validate_credentials
set -a
# This owner-only file is intentionally executable shell configuration. Its
# values are exported only to Compose and are never rendered into its YAML.
. "$credentials_path"
set +a
# Reassert the launcher-owned route after loading credentials so stale values
# cannot redirect learner data away from the verified loopback tunnel.
export ALGOHINT_GEMMA_BACKEND="transformers_http"
export ALGOHINT_GEMMA_DEPLOYMENT="remote"
export ALGOHINT_GEMMA_BASE_URL="http://127.0.0.1:18000/v1"

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
remote_control="${ALGOHINT_SSH_REMOTE_DOCKER_CONTROL:-$remote_app_root/current/scripts/docker-control.sh}"
for remote_path_name in remote_app_root remote_control; do
    remote_path="${!remote_path_name}"
    if [[ -z "$remote_path" || "$remote_path" == *$'\n'* ]]; then
        echo "$remote_path_name must be one non-empty remote path without newlines." >&2
        exit 2
    fi
done
quoted_control="$(quote_remote "$remote_control")"
health_url="http://127.0.0.1:$local_port/healthz"

remote_control_command() {
    local action="$1"
    ssh -T "$ssh_target" "$quoted_control $(quote_remote "$action")"
}

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
    echo "Remote Docker Gemma Server did not become ready within ${startup_timeout}s." >&2
    remote_control_command status >&2 || true
    return 1
}

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    if [[ -n "$monitor_pid" ]] && kill -0 "$monitor_pid" 2>/dev/null; then
        kill -TERM "$monitor_pid" 2>/dev/null || true
        wait "$monitor_pid" 2>/dev/null || true
    fi
    if [[ -n "$app_pid" ]]; then
        docker stop --time 10 "$container_name" >/dev/null 2>&1 || true
        wait "$app_pid" 2>/dev/null || true
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

if docker container inspect "$container_name" >/dev/null 2>&1; then
    echo "AlgoHint Docker container already exists: $container_name" >&2
    echo "Stop the owning launcher or inspect the stale container before retrying." >&2
    exit 2
fi
compose config --quiet
if [[ "$build_local" == true ]]; then
    compose build app
elif ! docker image inspect algohint:ssh-local >/dev/null 2>&1; then
    echo "AlgoHint SSH image is missing; omit --no-build-local for the first run." >&2
    exit 2
fi

if ssh -T "$ssh_target" "test -x $quoted_control"; then
    :
else
    control_check_exit=$?
    if ((control_check_exit == 255)); then
        echo "Could not verify the remote Gemma Docker control script over SSH." >&2
    else
        echo "Remote Gemma Docker control script is missing or not executable." >&2
        echo "Expected path: $remote_control" >&2
        echo "Install the pinned Gemma Server release before using this launcher." >&2
    fi
    exit 2
fi
if [[ "$build_remote" == true ]]; then
    remote_control_command build
fi
remote_status="$(remote_control_command status 2>&1 || true)"
if grep -qx "container: running" <<<"$remote_status"; then
    echo "Using the Gemma Docker container already running on $ssh_target."
elif grep -qx "container: not-running" <<<"$remote_status"; then
    remote_control_command start
    started_remote=true
else
    echo "Remote Gemma Docker status could not be determined safely." >&2
    printf '%s\n' "$remote_status" >&2
    exit 2
fi

ssh -N -T \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -L "127.0.0.1:$local_port:127.0.0.1:$remote_port" \
    "$ssh_target" &
tunnel_pid=$!
wait_for_tunnel

if ! algohint_requested_gemma_doctor "${app_arguments[@]}"; then
    if ! compose run --rm --no-deps app doctor --provider gemma; then
        echo "Gemma Server contract check failed; AlgoHint was not started." >&2
        exit 1
    fi
fi
compose run --rm --no-deps --name "$container_name" app "${app_arguments[@]}" &
app_pid=$!
algohint_monitor_gemma_health \
    "$health_url" \
    "$monitor_interval" \
    "$health_failure_threshold" \
    "Remote Docker Gemma Server or SSH tunnel health was lost after startup." &
monitor_pid=$!
set +e
wait "$app_pid"
app_exit=$?
set -e
app_pid=""
exit "$app_exit"
