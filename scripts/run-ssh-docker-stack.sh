#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
compose_file="$project_root/compose.ssh.yaml"
release_manifest="$project_root/config/gemma-server-release.conf"
public_docker_config="$project_root/config/public-docker-client"
remote_installer="${ALGOHINT_INSTALL_GEMMA_SERVER_SCRIPT:-$project_root/scripts/install-gemma-server-ssh.sh}"
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
public_docker_runtime_config=""

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
if [[ ! -r "$release_manifest" ]]; then
    echo "Gemma Server release manifest is missing: $release_manifest" >&2
    exit 2
fi
if [[ ! -f "$public_docker_config/config.json" ||
    -L "$public_docker_config/config.json" ]]; then
    echo "Public Docker client config must be a regular tracked file." >&2
    exit 2
fi
if [[ "$(tr -d '[:space:]' <"$public_docker_config/config.json")" != "{}" ]]; then
    echo "Public Docker client config must be the tracked empty JSON object." >&2
    exit 2
fi
expected_remote_commit="$(
    sed -n "s/^ALGOHINT_GEMMA_SERVER_COMMIT='\\([0-9a-f]\\{40\\}\\)'$/\\1/p" \
        "$release_manifest"
)"
if [[ ! "$expected_remote_commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Gemma Server release manifest has no valid full commit SHA." >&2
    exit 2
fi

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

read_remote_release() {
    local quoted_release
    quoted_release="$(quote_remote "$remote_app_root/current/RELEASE")"
    ssh -T "$ssh_target" \
        "if test -r $quoted_release; then sed -n 's/^commit=//p' $quoted_release; else printf 'missing\\n'; fi"
}

remote_controller_is_available() {
    ssh -T "$ssh_target" "test -x $quoted_control"
}

ensure_remote_release() {
    local actual_commit
    actual_commit="$(read_remote_release)"
    if [[ "$actual_commit" == "$expected_remote_commit" ]] &&
        remote_controller_is_available; then
        return
    fi

    if [[ "$build_remote" != true ]]; then
        echo "Remote Gemma Docker release is not ready." >&2
        echo "Expected commit: $expected_remote_commit" >&2
        echo "Current commit: $actual_commit" >&2
        echo "Retry with --build-remote to install and build the pinned release." >&2
        exit 2
    fi
    if [[ ! -x "$remote_installer" ]]; then
        echo "Pinned Gemma Server installer is missing: $remote_installer" >&2
        exit 2
    fi

    echo "Installing pinned Gemma Server release on $ssh_target: $expected_remote_commit"
    "$remote_installer"
    actual_commit="$(read_remote_release)"
    if [[ "$actual_commit" != "$expected_remote_commit" ]] ||
        ! remote_controller_is_available; then
        echo "Pinned Gemma Server installation did not produce the expected Docker controller." >&2
        echo "Expected commit: $expected_remote_commit" >&2
        echo "Current commit: $actual_commit" >&2
        exit 2
    fi
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
    if [[ -n "$public_docker_runtime_config" &&
        -d "$public_docker_runtime_config" &&
        ! -L "$public_docker_runtime_config" ]]; then
        rm -rf -- "$public_docker_runtime_config"
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
ensure_remote_release
if [[ "$build_local" == true ]]; then
    # Both base images are public and digest-pinned. Excluding the user's
    # registry credential helpers keeps secrets out of BuildKit sessions and
    # avoids Docker Desktop/WSL helper failures for anonymous GHCR metadata.
    # Buildx writes state beside config.json, so copy the empty config into an
    # owned temporary directory instead of mutating the tracked source tree.
    public_docker_runtime_config="$(
        mktemp -d "${TMPDIR:-/tmp}/algohint-public-docker.XXXXXX"
    )"
    install -m 600 \
        "$public_docker_config/config.json" \
        "$public_docker_runtime_config/config.json"
    DOCKER_CONFIG="$public_docker_runtime_config" compose build app
    rm -rf -- "$public_docker_runtime_config"
    public_docker_runtime_config=""
elif ! docker image inspect algohint:ssh-local >/dev/null 2>&1; then
    echo "AlgoHint SSH image is missing; omit --no-build-local for the first run." >&2
    exit 2
fi

if [[ "$build_remote" == true ]]; then
    remote_control_command build
fi
remote_status="$(remote_control_command status 2>&1 || true)"
if grep -qx "container: running" <<<"$remote_status"; then
    echo "Using the Gemma Docker container already running on $ssh_target."
elif grep -qx "container: not-running" <<<"$remote_status"; then
    # Claim cleanup responsibility before the blocking start call. If startup is
    # interrupted while the controller waits for model readiness, the remote
    # container already exists and must not be left in a restart/loading state.
    started_remote=true
    remote_control_command start
else
    echo "Remote Gemma Docker status could not be determined safely." >&2
    printf '%s\n' "$remote_status" >&2
    exit 2
fi

# Load client credentials only after installation and image operations finish;
# those steps neither need nor inherit provider secrets.
set -a
. "$credentials_path"
set +a
# Reassert the launcher-owned route after loading credentials so stale values
# cannot redirect learner data away from the verified loopback tunnel.
export ALGOHINT_GEMMA_BACKEND="transformers_http"
export ALGOHINT_GEMMA_DEPLOYMENT="remote"
export ALGOHINT_GEMMA_BASE_URL="http://127.0.0.1:18000/v1"
docker_operating_system="$(docker info --format '{{.OperatingSystem}}')"
if [[ "$docker_operating_system" == *"Docker Desktop"* ]]; then
    # Docker Desktop runs Linux containers in its VM, so container loopback is
    # not the WSL distribution that owns the tunnel.
    export ALGOHINT_GEMMA_CONTAINER_BASE_URL="http://host.docker.internal:18000/v1"
else
    export ALGOHINT_GEMMA_CONTAINER_BASE_URL="$ALGOHINT_GEMMA_BASE_URL"
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
