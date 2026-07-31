#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=scripts/lib/gemma-ssh-target.sh
. "$project_root/scripts/lib/gemma-ssh-target.sh"

usage() {
    cat <<'EOF'
Usage: sync-gemma-credentials-ssh.sh [--replace]

Copy only ALGOHINT_GEMMA_API_KEY from the protected remote Gemma credentials
into ~/.config/algohint/gemma-remote-credentials.
EOF
}

replace_existing=false
if [[ "${1:-}" == "--replace" ]]; then
    replace_existing=true
    shift
fi
if [[ "$#" -ne 0 ]]; then
    usage >&2
    exit 2
fi

ssh_target="$(algohint_read_gemma_ssh_target)"

if ! command -v ssh >/dev/null 2>&1 || ! command -v base64 >/dev/null 2>&1; then
    echo "ssh and base64 are required to synchronize Gemma credentials." >&2
    exit 2
fi
credentials_dir="$HOME/.config/algohint"
credentials_path="$credentials_dir/gemma-remote-credentials"
garbage_dir="$credentials_dir/_GARBAGE"

if [[ -e "$credentials_dir" || -L "$credentials_dir" ]]; then
    if [[ ! -d "$credentials_dir" || -L "$credentials_dir" ]]; then
        echo "Local credentials directory must be a non-symlink directory: $credentials_dir" >&2
        exit 2
    fi
    if [[ "$(stat -c '%u' "$credentials_dir")" != "$(id -u)" ]]; then
        echo "Local credentials directory must be owned by the current user." >&2
        exit 2
    fi
else
    install -d -m 700 "$credentials_dir"
fi
chmod 700 "$credentials_dir"

validate_existing_credentials() {
    if [[ ! -f "$credentials_path" || -L "$credentials_path" ]]; then
        echo "Existing local credentials must be a regular non-symlink file." >&2
        return 1
    fi
    if [[ "$(stat -c '%u' "$credentials_path")" != "$(id -u)" ]]; then
        echo "Existing local credentials must be owned by the current user." >&2
        return 1
    fi
    local mode
    mode="$(stat -c '%a' "$credentials_path")"
    if (( (8#$mode & 077) != 0 )); then
        echo "Existing local credentials must not grant group or world permissions." >&2
        return 1
    fi
}

if [[ -e "$credentials_path" || -L "$credentials_path" ]]; then
    validate_existing_credentials || exit 2
fi

# Stream only the client API key; copying the remote file would also expose
# Hugging Face tokens and server-only compatibility settings.
encoded_key="$(
    ssh -T "$ssh_target" 'bash -s' <<'REMOTE'
set -euo pipefail
set +x

if ! command -v base64 >/dev/null 2>&1; then
    echo "base64 is required on the GPU host." >&2
    exit 2
fi

credentials_path="${XDG_CONFIG_HOME:-$HOME/.config}/algohint-gemma-server/credentials"
if [[ ! -f "$credentials_path" || -L "$credentials_path" ]]; then
    echo "Remote Gemma credentials must be a regular non-symlink file." >&2
    exit 2
fi
if [[ "$(stat -c '%u' "$credentials_path")" != "$(id -u)" ]]; then
    echo "Remote Gemma credentials must be owned by the current user." >&2
    exit 2
fi
credentials_mode="$(stat -c '%a' "$credentials_path")"
if (( (8#$credentials_mode & 077) != 0 )); then
    echo "Remote Gemma credentials must not grant group or world permissions." >&2
    exit 2
fi

set -a
. "$credentials_path"
set +a

api_key="${ALGOHINT_GEMMA_API_KEY:-}"
if [[ -z "$api_key" || "$api_key" == *$'\n'* ]]; then
    echo "Remote ALGOHINT_GEMMA_API_KEY is missing or invalid." >&2
    exit 2
fi
printf '%s' "$api_key" | base64 | tr -d '\n'
REMOTE
)"

if [[ -z "$encoded_key" || "$encoded_key" == *$'\n'* ]] ||
    [[ ! "$encoded_key" =~ ^[A-Za-z0-9+/]+={0,2}$ ]]; then
    echo "Remote credential response was not one valid Base64 value." >&2
    exit 2
fi

api_key="$(printf '%s' "$encoded_key" | base64 --decode)"
unset encoded_key
if [[ -z "$api_key" || "$api_key" == *$'\n'* ]]; then
    echo "Decoded remote API key was empty or invalid." >&2
    exit 2
fi

# Build the protected file beside its destination and rename atomically so an
# interrupted SSH transfer never becomes the active credentials file.
temporary_path="$(mktemp "$credentials_dir/.gemma-remote-credentials.XXXXXX.tmp")"
cleanup_temporary() {
    if [[ -n "${temporary_path:-}" && -e "$temporary_path" ]]; then
        rm -f -- "$temporary_path"
    fi
}
trap cleanup_temporary EXIT INT TERM
chmod 600 "$temporary_path"
printf 'ALGOHINT_GEMMA_API_KEY=%q\n' "$api_key" >"$temporary_path"
unset api_key

if [[ -e "$credentials_path" ]]; then
    if cmp -s -- "$temporary_path" "$credentials_path"; then
        echo "Gemma client credentials are already synchronized: $credentials_path"
        exit 0
    fi
    if [[ "$replace_existing" == false ]]; then
        echo "Local Gemma credentials differ; rerun with --replace after verification." >&2
        exit 2
    fi

    if [[ -e "$garbage_dir" || -L "$garbage_dir" ]]; then
        if [[ ! -d "$garbage_dir" || -L "$garbage_dir" ]]; then
            echo "Credential garbage path must be a non-symlink directory." >&2
            exit 2
        fi
        if [[ "$(stat -c '%u' "$garbage_dir")" != "$(id -u)" ]]; then
            echo "Credential garbage directory must be owned by the current user." >&2
            exit 2
        fi
    else
        install -d -m 700 "$garbage_dir"
    fi
    chmod 700 "$garbage_dir"
    backup_path="$garbage_dir/gemma-remote-credentials.$(date -u +%Y%m%dT%H%M%SZ).$$"
    if [[ -e "$backup_path" || -L "$backup_path" ]]; then
        echo "Credential backup target already exists; refusing to overwrite it." >&2
        exit 2
    fi
    # Preserve the old inode under _GARBAGE before the atomic replacement.
    ln -- "$credentials_path" "$backup_path"
    chmod 600 "$backup_path"
    echo "Previous Gemma client credentials preserved at: $backup_path"
fi

mv -f -- "$temporary_path" "$credentials_path"
temporary_path=""
trap - EXIT INT TERM
chmod 600 "$credentials_path"
echo "Gemma client credentials synchronized: $credentials_path"
