#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
manifest="$project_root/config/gemma-server-release.conf"
remote_bootstrap="$project_root/scripts/bootstrap-gemma-server-remote.sh"
# shellcheck source=scripts/lib/gemma-ssh-target.sh
. "$project_root/scripts/lib/gemma-ssh-target.sh"
# shellcheck source=scripts/lib/gemma-ssh-runtime.sh
. "$project_root/scripts/lib/gemma-ssh-runtime.sh"
ssh_target="$(algohint_read_gemma_ssh_target)"

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

# Installing a fixed release changes the shared `current` pointer. Require the
# operator to stop the owning runtime explicitly instead of letting deployment
# infer ownership from the launch mode that happened to invoke this script.
if ! algohint_refresh_remote_runtime_state "$ssh_target" "$install_root"; then
    echo "Could not inspect the remote Gemma release and runtime state." >&2
    exit 2
fi
if [[ "$ALGOHINT_REMOTE_NATIVE_STATE" == "unknown" ||
    "$ALGOHINT_REMOTE_DOCKER_STATE" == "unknown" ]]; then
    echo "A remote Gemma controller returned an ambiguous state." >&2
    exit 2
fi
if [[ "$ALGOHINT_REMOTE_NATIVE_STATE" == "running" ||
    "$ALGOHINT_REMOTE_DOCKER_STATE" == "running" ]]; then
    algohint_print_remote_stop_guidance
    exit 2
fi

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
