#!/usr/bin/env bash

# Inspect remote Gemma ownership without reading credentials or trusting
# controller prose as shell input. Callers receive only closed key/value states.

algohint_quote_remote_runtime_value() {
    local value="${1//\'/\'\\\'\'}"
    printf "'%s'" "$value"
}

algohint_remote_runtime_snapshot() {
    local ssh_target="$1"
    local remote_app_root="$2"
    local quoted_root
    quoted_root="$(algohint_quote_remote_runtime_value "$remote_app_root")"

    ssh -T "$ssh_target" "bash -s -- $quoted_root" <<'REMOTE'
set -euo pipefail
install_root="$1"
current="$install_root/current"
native_control="$current/scripts/server-control.sh"
docker_control="$current/scripts/docker-control.sh"

release="missing"
if [[ -r "$current/RELEASE" ]]; then
    release="$(sed -n 's/^commit=\([0-9a-f]\{40\}\)$/\1/p' "$current/RELEASE")"
    [[ -n "$release" ]] || release="invalid"
fi

native="missing"
if [[ -x "$native_control" ]]; then
    native_status="$(
        ALGOHINT_GEMMA_INSTALL_ROOT="$install_root" \
            "$native_control" status 2>&1 || true
    )"
    if grep -qE '^tmux: running|^process: running' <<<"$native_status"; then
        native="running"
    elif grep -q '^tmux: not-running' <<<"$native_status" &&
        grep -q '^process: not-running' <<<"$native_status"; then
        native="stopped"
    else
        native="unknown"
    fi
fi

docker="missing"
if [[ -x "$docker_control" ]]; then
    docker_status="$("$docker_control" status 2>&1 || true)"
    if grep -q '^container: running$' <<<"$docker_status"; then
        docker="running"
    elif grep -q '^container: not-running$' <<<"$docker_status"; then
        docker="stopped"
    else
        docker="unknown"
    fi
fi

health="unavailable"
if command -v curl >/dev/null 2>&1; then
    health_body="$(
        curl --silent --fail --max-time 2 \
            http://127.0.0.1:18080/healthz 2>/dev/null || true
    )"
    if grep -Eq '"ready"[[:space:]]*:[[:space:]]*true' <<<"$health_body"; then
        health="ready"
    elif [[ -n "$health_body" ]]; then
        health="unexpected"
    fi
fi

printf 'release=%s\nnative=%s\ndocker=%s\nhealth=%s\n' \
    "$release" "$native" "$docker" "$health"
REMOTE
}

algohint_refresh_remote_runtime_state() {
    local ssh_target="$1"
    local remote_app_root="$2"
    local snapshot
    if ! snapshot="$(
        algohint_remote_runtime_snapshot "$ssh_target" "$remote_app_root"
    )"; then
        return 1
    fi
    ALGOHINT_REMOTE_RELEASE="$(sed -n 's/^release=//p' <<<"$snapshot")"
    ALGOHINT_REMOTE_NATIVE_STATE="$(sed -n 's/^native=//p' <<<"$snapshot")"
    ALGOHINT_REMOTE_DOCKER_STATE="$(sed -n 's/^docker=//p' <<<"$snapshot")"
    ALGOHINT_REMOTE_HEALTH_STATE="$(sed -n 's/^health=//p' <<<"$snapshot")"
    [[ "$ALGOHINT_REMOTE_RELEASE" =~ ^([0-9a-f]{40}|missing|invalid)$ ]] &&
        [[ "$ALGOHINT_REMOTE_NATIVE_STATE" =~ ^(running|stopped|missing|unknown)$ ]] &&
        [[ "$ALGOHINT_REMOTE_DOCKER_STATE" =~ ^(running|stopped|missing|unknown)$ ]] &&
        [[ "$ALGOHINT_REMOTE_HEALTH_STATE" =~ ^(ready|unavailable|unexpected)$ ]]
}

algohint_print_remote_stop_guidance() {
    cat >&2 <<'MESSAGE'
A managed Gemma runtime must be stopped before switching releases.
Run on the AlgoHint host:
  ./scripts/stop-gemma-server-ssh.sh
Then retry the original command.
MESSAGE
}
