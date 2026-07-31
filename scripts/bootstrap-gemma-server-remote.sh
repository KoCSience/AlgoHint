#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

# This script runs on the GPU host. It checks out the pinned public commit into
# a temporary worktree and delegates all release mutation to that commit's
# reviewed deployment script.
if [[ "$#" -ne 4 ]]; then
    echo "Usage: $0 <repository> <full-commit-sha> <install-root> <source-cache>" >&2
    exit 2
fi
repository="$1"
commit="$2"
install_root="$3"
source_cache="$4"

if [[ -z "$repository" || "$repository" == -* || "$repository" == *$'\n'* ]]; then
    echo "Repository must be one safe Git remote." >&2
    exit 2
fi
if [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Gemma Server commit must be a full lowercase SHA." >&2
    exit 2
fi
for path_name in install_root source_cache; do
    path_value="${!path_name}"
    if [[ "$path_value" != /* || "$path_value" == "/" || "$path_value" == "$HOME" ]] ||
        [[ "$path_value" == *$'\n'* ]]; then
        echo "$path_name must be a safe absolute application path." >&2
        exit 2
    fi
done
if ! command -v git >/dev/null 2>&1; then
    echo "git is required on the Gemma Server host." >&2
    exit 2
fi
if command -v uv >/dev/null 2>&1; then
    uv_bin="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then
    # Non-interactive SSH commonly omits the per-user binary directory even
    # though the reviewed uv installer placed the pinned tool there.
    uv_bin="$HOME/.local/bin/uv"
else
    echo "uv is required on the Gemma Server host." >&2
    exit 2
fi
uv_bin_dir="$(dirname -- "$uv_bin")"
export PATH="$uv_bin_dir:$PATH"

source_parent="$(dirname -- "$source_cache")"
install -d -m 700 "$source_parent"
if [[ ! -e "$source_cache" ]]; then
    git clone --bare -- "$repository" "$source_cache"
elif [[ ! -d "$source_cache" ]]; then
    echo "Source cache exists but is not a directory: $source_cache" >&2
    exit 2
fi
cached_repository="$(git -C "$source_cache" remote get-url origin)"
if [[ "$cached_repository" != "$repository" ]]; then
    echo "Source cache origin does not match the release manifest." >&2
    exit 2
fi

# Bare caches created by older bootstrap versions can have no fetch refspec.
# Fetch every advertised branch and tag explicitly so an immutable commit on a
# reviewed non-default branch is available without falling back to remote HEAD.
git -C "$source_cache" fetch --prune --prune-tags origin \
    '+refs/heads/*:refs/remotes/origin/*' \
    '+refs/tags/*:refs/tags/*'
resolved_commit="$(git -C "$source_cache" rev-parse --verify "$commit^{commit}")"
if [[ "$resolved_commit" != "$commit" ]]; then
    echo "Fetched object did not resolve to the pinned Gemma Server commit." >&2
    exit 2
fi

worktree="$(mktemp -d "${TMPDIR:-/tmp}/algohint-gemma-release.XXXXXX")"
worktree_registered=false
cleanup_worktree() {
    if [[ "$worktree_registered" == true ]]; then
        git -C "$source_cache" worktree remove --force "$worktree" 2>/dev/null || true
    elif [[ -d "$worktree" ]]; then
        failed_root="$install_root/_GARBAGE"
        install -d -m 700 "$failed_root"
        mv -- "$worktree" "$failed_root/bootstrap-worktree-$commit-$$"
    fi
}
trap cleanup_worktree EXIT

git -C "$source_cache" worktree add --detach "$worktree" "$commit"
worktree_registered=true
if [[ ! -x "$worktree/scripts/deploy-release.sh" ]]; then
    echo "Pinned Gemma Server commit has no executable deployment script." >&2
    exit 2
fi
ALGOHINT_GEMMA_INSTALL_ROOT="$install_root" \
    "$worktree/scripts/deploy-release.sh" "$commit"

git -C "$source_cache" worktree remove --force "$worktree"
worktree_registered=false
trap - EXIT
