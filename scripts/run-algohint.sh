#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
credentials_path="${ALGOHINT_CREDENTIALS:-$HOME/.config/algohint/credentials}"

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
