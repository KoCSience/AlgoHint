#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
credentials_path="${ALGOHINT_CREDENTIALS:-$HOME/.config/algohint/credentials}"
managed_gemma_deployment="${ALGOHINT_MANAGED_GEMMA_DEPLOYMENT:-}"
managed_gemma_base_url="${ALGOHINT_MANAGED_GEMMA_BASE_URL:-}"

if [[ -r "$credentials_path" ]]; then
    set -a
    # The application never discovers files implicitly. This explicit launcher
    # is the only boundary that imports user-managed provider credentials.
    . "$credentials_path"
    set +a
else
    echo "AlgoHint credentials were not loaded: $credentials_path" >&2
    echo "The app will still start and unavailable providers will fall back safely." >&2
fi

apply_managed_gemma_configuration() {
    local managed_port
    if [[ -z "$managed_gemma_deployment" && -z "$managed_gemma_base_url" ]]; then
        return
    fi
    if [[ "$managed_gemma_deployment" != "local" &&
        "$managed_gemma_deployment" != "remote" ]]; then
        echo "Managed Gemma deployment must be local or remote." >&2
        exit 2
    fi
    if [[ ! "$managed_gemma_base_url" =~ ^http://127\.0\.0\.1:([1-9][0-9]*)/v1$ ]]; then
        echo "Managed Gemma base URL must use a loopback HTTP endpoint ending in /v1." >&2
        exit 2
    fi
    managed_port="${BASH_REMATCH[1]}"
    if ((managed_port > 65535)); then
        echo "Managed Gemma port must be between 1 and 65535." >&2
        exit 2
    fi

    # Managed stack launchers own this connection path. Reapply their
    # non-secret values after credential loading so a stale credential file
    # cannot redirect learner data away from the verified tunnel or listener.
    export ALGOHINT_GEMMA_BACKEND="transformers_http"
    export ALGOHINT_GEMMA_DEPLOYMENT="$managed_gemma_deployment"
    export ALGOHINT_GEMMA_BASE_URL="$managed_gemma_base_url"
}

apply_managed_gemma_configuration
unset ALGOHINT_MANAGED_GEMMA_DEPLOYMENT ALGOHINT_MANAGED_GEMMA_BASE_URL

if [[ -n "${ALGOHINT_UV_BIN:-}" ]]; then
    uv_bin="$ALGOHINT_UV_BIN"
elif command -v uv >/dev/null 2>&1; then
    uv_bin="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then
    uv_bin="$HOME/.local/bin/uv"
else
    echo "uv is required. Install uv and run 'uv sync --frozen' in $project_root." >&2
    exit 2
fi
if [[ ! -x "$uv_bin" ]]; then
    echo "Configured uv executable is not executable: $uv_bin" >&2
    exit 2
fi
if [[ ! -f "$project_root/uv.lock" ]]; then
    echo "AlgoHint lock file is missing: $project_root/uv.lock" >&2
    exit 2
fi

cd "$project_root"
exec "$uv_bin" run --frozen --no-sync algohint --data-dir "$project_root/data" "$@"
