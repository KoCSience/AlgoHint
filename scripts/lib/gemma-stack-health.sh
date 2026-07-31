#!/usr/bin/env bash

# Shared, side-effect-free probes for launchers that own a Gemma connection path.

algohint_gemma_is_ready() {
    local health_url="$1"
    curl --silent --fail --max-time 2 "$health_url" 2>/dev/null |
        grep -Eq '"ready"[[:space:]]*:[[:space:]]*true'
}

algohint_requested_gemma_doctor() {
    local argument
    local previous=""
    local found_doctor=false
    local found_gemma_provider=false
    for argument in "$@"; do
        if [[ "$argument" == "doctor" ]]; then
            found_doctor=true
        elif [[ "$previous" == "--provider" && "$argument" == "gemma" ]] ||
            [[ "$argument" == "--provider=gemma" ]]; then
            found_gemma_provider=true
        fi
        previous="$argument"
    done
    [[ "$found_doctor" == true && "$found_gemma_provider" == true ]]
}

algohint_verify_gemma_contract() {
    local algohint_runner="$1"
    shift
    if algohint_requested_gemma_doctor "$@"; then
        return
    fi
    if ! "$algohint_runner" doctor --provider gemma; then
        echo "Gemma Server contract check failed; AlgoHint was not started." >&2
        return 1
    fi
}

algohint_monitor_gemma_health() {
    local health_url="$1"
    local monitor_interval="$2"
    local failure_threshold="$3"
    local failure_summary="$4"
    local consecutive_failures=0
    local delay_pid=""
    trap 'if [[ -n "$delay_pid" ]]; then kill -TERM "$delay_pid" 2>/dev/null || true; fi; exit 0' \
        TERM INT

    while true; do
        sleep "$monitor_interval" &
        delay_pid=$!
        wait "$delay_pid"
        delay_pid=""
        if algohint_gemma_is_ready "$health_url"; then
            consecutive_failures=0
            continue
        fi
        ((consecutive_failures += 1))
        if ((consecutive_failures >= failure_threshold)); then
            # Monitoring reports only: automatic restarts could take ownership
            # of an external server, while the app can safely continue locally.
            echo "$failure_summary" >&2
            echo "AlgoHint remains running with RuleBased fallback." >&2
            echo "Restart this stack and run doctor --provider gemma before retrying." >&2
            return
        fi
    done
}
