#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

# Resolve every executable explicitly because tmux does not necessarily load
# the interactive shell configuration that exposes the account's uv path.
app_root="${ALGOHINT_GEMMA_APP_ROOT:-$HOME/programs/algohint-gemma-server}"
code_root="${ALGOHINT_GEMMA_CODE_ROOT:-$app_root/current}"
credentials_path="${ALGOHINT_GEMMA_CREDENTIALS:-$HOME/.config/algohint-gemma-server/credentials}"
state_dir="${ALGOHINT_GEMMA_STATE_DIR:-$app_root/state}"
status_file="${ALGOHINT_GEMMA_STATUS_FILE:-$state_dir/status.json}"
pid_file="${ALGOHINT_GEMMA_PID_FILE:-$state_dir/server.pid}"

if [[ ! -r "$credentials_path" ]]; then
    echo "Gemma credentials file is not readable: $credentials_path" >&2
    exit 2
fi
if [[ ! -x "$app_root/.venv/bin/uvicorn" ]]; then
    echo "Gemma Uvicorn executable is missing: $app_root/.venv/bin/uvicorn" >&2
    exit 2
fi

install -d -m 700 "$state_dir"

set -a
# This is an explicitly configured credentials shell fragment, not a dotenv file.
# Keep xtrace disabled so secret values cannot be echoed while it is sourced.
. "$credentials_path"
set +a

export HF_HOME="${HF_HOME:-$app_root/cache/huggingface}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$app_root/cache/uv}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2}"
export ALGOHINT_GEMMA_STATUS_FILE="$status_file"
export PYTHONUNBUFFERED=1

cd "$code_root"

"$app_root/.venv/bin/uvicorn" \
    algohint_gemma_server.app:create_app \
    --factory \
    --host 127.0.0.1 \
    --port "${ALGOHINT_GEMMA_PORT:-18080}" \
    --log-level info \
    --no-access-log &
server_pid=$!

# The PID file is replaced atomically so stop never acts on a partially written ID.
pid_tmp="$pid_file.$$"
printf '%s\n' "$server_pid" >"$pid_tmp"
chmod 600 "$pid_tmp"
mv -f "$pid_tmp" "$pid_file"

set +e
wait "$server_pid"
exit_code=$?
set -e

"$app_root/.venv/bin/python" \
    -m algohint_gemma_server.status process-exit "$exit_code" || true
exit "$exit_code"
