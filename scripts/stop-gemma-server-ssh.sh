#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=scripts/lib/gemma-ssh-target.sh
. "$project_root/scripts/lib/gemma-ssh-target.sh"
# shellcheck source=scripts/lib/gemma-ssh-runtime.sh
. "$project_root/scripts/lib/gemma-ssh-runtime.sh"

operation="stop"
mode="auto"
while (($# > 0)); do
    case "$1" in
        --status)
            [[ "$operation" == "stop" && "$mode" == "auto" ]] || {
                echo "--status cannot be combined with a stop mode." >&2
                exit 2
            }
            operation="status"
            ;;
        --mode)
            [[ "$operation" == "stop" && "$mode" == "auto" && $# -ge 2 ]] || {
                echo "--mode requires exactly one stop mode." >&2
                exit 2
            }
            mode="$2"
            shift
            [[ "$mode" == "native" || "$mode" == "docker" ]] || {
                echo "--mode must be native or docker." >&2
                exit 2
            }
            ;;
        --all)
            [[ "$operation" == "stop" && "$mode" == "auto" ]] || {
                echo "--all cannot be combined with another mode." >&2
                exit 2
            }
            mode="all"
            ;;
        *)
            echo "Usage: $0 [--status | --mode native | --mode docker | --all]" >&2
            exit 2
            ;;
    esac
    shift
done

ssh_target="$(algohint_read_gemma_ssh_target)"
if [[ -n "${ALGOHINT_SSH_REMOTE_APP_ROOT:-}" ]]; then
    remote_app_root="$ALGOHINT_SSH_REMOTE_APP_ROOT"
else
    if ! remote_home="$(ssh -T "$ssh_target" 'printf "%s\n" "$HOME"')"; then
        echo "Could not resolve the remote home directory over SSH." >&2
        exit 2
    fi
    if [[ -z "$remote_home" || "$remote_home" != /* || "$remote_home" == *$'\n'* ]]; then
        echo "Could not resolve a safe remote home directory." >&2
        exit 2
    fi
    remote_app_root="$remote_home/programs/algohint-gemma-server"
fi
if [[ "$remote_app_root" != /* || "$remote_app_root" == "/" ||
    "$remote_app_root" == *$'\n'* ]]; then
    echo "ALGOHINT_SSH_REMOTE_APP_ROOT must be one safe absolute remote path." >&2
    exit 2
fi

read_snapshot() {
    if ! algohint_refresh_remote_runtime_state "$ssh_target" "$remote_app_root"; then
        echo "Could not inspect managed Gemma runtimes over SSH." >&2
        exit 2
    fi
    release="$ALGOHINT_REMOTE_RELEASE"
    native_state="$ALGOHINT_REMOTE_NATIVE_STATE"
    docker_state="$ALGOHINT_REMOTE_DOCKER_STATE"
    health_state="$ALGOHINT_REMOTE_HEALTH_STATE"
}

print_snapshot() {
    printf 'release: %s\nnative: %s\ndocker: %s\nhealthz: %s\n' \
        "$release" "$native_state" "$docker_state" "$health_state"
}

if ! read_snapshot; then
    echo "Remote Gemma runtime status did not match the closed contract." >&2
    exit 2
fi
print_snapshot
if [[ "$operation" == "status" ]]; then
    exit 0
fi
if [[ "$native_state" == "unknown" || "$docker_state" == "unknown" ]]; then
    echo "A controller returned an ambiguous status; no runtime was stopped." >&2
    exit 2
fi
if [[ "$native_state" == "missing" && "$docker_state" == "missing" ]]; then
    echo "No managed Gemma controller is installed in the current release." >&2
    exit 2
fi

if [[ "$mode" == "auto" ]]; then
    if [[ "$native_state" == "running" && "$docker_state" == "running" ]]; then
        echo "Both Gemma runtimes are active; use --all or one explicit --mode." >&2
        exit 2
    elif [[ "$native_state" == "running" ]]; then
        mode="native"
    elif [[ "$docker_state" == "running" ]]; then
        mode="docker"
    else
        echo "Managed Gemma runtimes are already stopped."
        exit 0
    fi
fi

quote_remote() {
    algohint_quote_remote_runtime_value "$1"
}
stop_native() {
    [[ "$native_state" != "missing" ]] || return
    local control="$remote_app_root/current/scripts/server-control.sh"
    ssh -T "$ssh_target" \
        "ALGOHINT_GEMMA_INSTALL_ROOT=$(quote_remote "$remote_app_root") $(quote_remote "$control") stop"
}
stop_docker() {
    [[ "$docker_state" != "missing" ]] || return
    local control="$remote_app_root/current/scripts/docker-control.sh"
    ssh -T "$ssh_target" "$(quote_remote "$control") stop"
}

case "$mode" in
    native) stop_native ;;
    docker) stop_docker ;;
    all)
        stop_native
        stop_docker
        ;;
esac

if ! read_snapshot; then
    echo "Could not verify Gemma runtime state after stop." >&2
    exit 2
fi
print_snapshot
case "$mode" in
    native) [[ "$native_state" =~ ^(stopped|missing)$ ]] ;;
    docker) [[ "$docker_state" =~ ^(stopped|missing)$ ]] ;;
    all)
        [[ "$native_state" =~ ^(stopped|missing)$ ]] &&
            [[ "$docker_state" =~ ^(stopped|missing)$ ]] &&
            [[ "$health_state" == "unavailable" ]]
        ;;
esac || {
    echo "The selected Gemma runtime did not reach a verified stopped state." >&2
    exit 1
}
echo "Managed Gemma runtime stop completed."
