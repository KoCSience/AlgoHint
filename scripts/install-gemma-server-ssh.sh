#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
manifest="$project_root/config/gemma-server-release.conf"
remote_bootstrap="$project_root/scripts/bootstrap-gemma-server-remote.sh"
ssh_target="${ALGOHINT_SSH_TARGET:-}"

if [[ -z "$ssh_target" || "$ssh_target" == -* || "$ssh_target" == *$'\n'* ]]; then
    echo "ALGOHINT_SSH_TARGET must be one SSH host or configured alias." >&2
    exit 2
fi
if ! command -v ssh >/dev/null 2>&1; then
    echo "ssh is required to install the remote Gemma Server." >&2
    exit 2
fi
if [[ ! -r "$manifest" || ! -r "$remote_bootstrap" ]]; then
    echo "Gemma Server release manifest or remote bootstrap is missing." >&2
    exit 2
fi

# This tracked file contains only a public URL and immutable commit SHA.
# Validate both again before constructing the remote shell command.
. "$manifest"
repository="${ALGOHINT_GEMMA_SERVER_REPOSITORY:-}"
commit="${ALGOHINT_GEMMA_SERVER_COMMIT:-}"
if [[ "$repository" != "https://github.com/KoCSience/AlgoHint-Gemma-Server.git" ]] ||
    [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Gemma Server release manifest is invalid." >&2
    exit 2
fi

remote_home="$(ssh -T "$ssh_target" 'printf "%s\n" "$HOME"')"
if [[ -z "$remote_home" || "$remote_home" != /* || "$remote_home" == *$'\n'* ]]; then
    echo "Could not resolve a safe remote home directory." >&2
    exit 2
fi
install_root="${ALGOHINT_SSH_REMOTE_APP_ROOT:-$remote_home/programs/algohint-gemma-server}"
source_cache="${ALGOHINT_SSH_GEMMA_SOURCE_CACHE:-$remote_home/.cache/algohint-gemma-server/source.git}"
for path_name in install_root source_cache; do
    path_value="${!path_name}"
    if [[ "$path_value" != /* || "$path_value" == "/" || "$path_value" == *$'\n'* ]]; then
        echo "$path_name must be one safe absolute remote path." >&2
        exit 2
    fi
done

quote_remote() {
    local value="${1//\'/\'\\\'\'}"
    printf "'%s'" "$value"
}

remote_command="bash -s --"
for value in "$repository" "$commit" "$install_root" "$source_cache"; do
    remote_command+=" $(quote_remote "$value")"
done
ssh -T "$ssh_target" "$remote_command" <"$remote_bootstrap"

echo "Pinned Gemma Server release installed on $ssh_target."
echo "Next: create the documented remote credentials, run preflight, then start the controller."
