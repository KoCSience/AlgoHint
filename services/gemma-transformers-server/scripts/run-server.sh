#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

# Resolve every executable explicitly because tmux does not necessarily load
# the interactive shell configuration that exposes the saeki user's uv path.
app_root="${ALGOHINT_GEMMA_APP_ROOT:-$HOME/programs/algohint-gemma-server}"
credentials_path="${ALGOHINT_GEMMA_CREDENTIALS:-$HOME/.config/algohint-gemma-server/credentials}"

set -a
. "$credentials_path"
set +a

export HF_HOME="${HF_HOME:-$app_root/cache/huggingface}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$app_root/cache/uv}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2}"

exec "$app_root/.venv/bin/uvicorn" \
    algohint_gemma_server.app:create_app \
    --factory \
    --host 127.0.0.1 \
    --port 18080 \
    --no-access-log

