#!/usr/bin/env bash
set -euo pipefail
set +x

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=scripts/lib/gemma-ssh-target.sh
. "$project_root/scripts/lib/gemma-ssh-target.sh"

if (($# != 0)); then
    echo "Usage: check-gemma-ssh.sh" >&2
    exit 2
fi

ssh_target="$(algohint_read_gemma_ssh_target)"

if ! command -v ssh >/dev/null 2>&1; then
    echo "ssh is required to check the remote Gemma host." >&2
    exit 2
fi

# Run the smallest portable remote command and print the success marker
# locally. This avoids depending on how the remote login shell parses printf.
set +e
ssh -T "$ssh_target" true
ssh_exit=$?
set -e
if ((ssh_exit != 0)); then
    echo "SSH connection check failed for Gemma host: $ssh_target" >&2
    exit "$ssh_exit"
fi

printf 'SSH connection OK: AlgoHint host -> GPU host (target: %s)\n' "$ssh_target"
