#!/usr/bin/env bash
set -euo pipefail
set +x

# This helper is streamed over one SSH session and runs on the GPU host. It
# waits there so local port forwarding is not opened before Uvicorn starts
# listening after the model has loaded.
if [[ "$#" -ne 4 ]]; then
    echo "Usage: $0 <control-script> <timeout-seconds> <progress-interval> <process-grace>" >&2
    exit 2
fi
control_script="$1"
startup_timeout="$2"
progress_interval="$3"
process_grace="$4"
health_url="http://127.0.0.1:18080/healthz"

validated_integer() {
    local name="$1"
    local value="$2"
    local minimum="$3"
    local maximum="$4"
    if [[ ! "$value" =~ ^[0-9]+$ ]] || ((value < minimum || value > maximum)); then
        echo "$name must be between $minimum and $maximum." >&2
        exit 2
    fi
}

if [[ "$control_script" != /* || "$control_script" == *$'\n'* ]] ||
    [[ ! -x "$control_script" ]]; then
    echo "Remote Gemma control script must be one executable absolute path." >&2
    exit 2
fi
validated_integer "timeout-seconds" "$startup_timeout" 1 3600
validated_integer "progress-interval" "$progress_interval" 1 60
validated_integer "process-grace" "$process_grace" 1 60

print_failure_context() {
    local summary="$1"
    echo "$summary" >&2
    "$control_script" status >&2 || true
    echo "Recent Gemma Server logs:" >&2
    "$control_script" logs 2>&1 | tail -n 40 >&2 || true
}

for ((elapsed = 0; elapsed < startup_timeout; elapsed++)); do
    if curl --silent --fail --max-time 2 "$health_url" 2>/dev/null |
        grep -Eq '"ready"[[:space:]]*:[[:space:]]*true'; then
        echo "Remote Gemma Server is ready after ${elapsed}s."
        exit 0
    fi

    if ((elapsed == 0 || elapsed == process_grace || elapsed % progress_interval == 0)); then
        status="$("$control_script" status 2>&1 || true)"
        process_state="$(sed -n '/^process: /{p;q;}' <<<"$status")"
        runtime_state="$(sed -n 's/^  state: //p' <<<"$status" | head -n 1)"
        runtime_state="${runtime_state:-starting}"
        echo "Waiting for remote Gemma Server: elapsed=${elapsed}s state=$runtime_state"
        if ((elapsed >= process_grace)) &&
            [[ "$process_state" != process:\ running* ]]; then
            print_failure_context \
                "Remote Gemma Server process exited before becoming ready."
            exit 1
        fi
    fi
    sleep 1
done

print_failure_context \
    "Remote Gemma Server did not become ready within ${startup_timeout}s."
exit 1
