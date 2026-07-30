#!/usr/bin/env bash

# Read the user-selected Gemma SSH alias as data, never as shell code. Keeping
# this validation in one place prevents the installer, credential synchronizer,
# and launcher from silently selecting different hosts.
algohint_read_gemma_ssh_target() {
    local target_path="$HOME/.config/algohint/gemma-ssh-target"
    local target_dir="${target_path%/*}"
    local owner_uid=""
    local mode=""
    local size=""
    local target=""
    local -a target_lines=()

    if [[ "${ALGOHINT_SSH_TARGET+x}" == "x" ]]; then
        echo "ALGOHINT_SSH_TARGET is no longer supported." >&2
        echo "Run: unset ALGOHINT_SSH_TARGET" >&2
        echo "Store one SSH alias in: $target_path" >&2
        return 2
    fi

    if [[ ! -e "$target_dir" && ! -L "$target_dir" ]]; then
        echo "Gemma configuration directory is missing: $target_dir" >&2
        echo "Create it with mode 700 before adding gemma-ssh-target." >&2
        return 2
    fi
    if [[ ! -d "$target_dir" || -L "$target_dir" ]]; then
        echo "Gemma configuration directory must be a non-symlink directory: $target_dir" >&2
        return 2
    fi
    if ! read -r owner_uid mode < <(stat -c '%u %a' "$target_dir"); then
        echo "Could not inspect the Gemma configuration directory: $target_dir" >&2
        return 2
    fi
    if [[ "$owner_uid" != "$(id -u)" || "$mode" != "700" ]]; then
        echo "Gemma configuration directory must be owned by the current user with mode 700: $target_dir" >&2
        return 2
    fi

    if [[ ! -e "$target_path" && ! -L "$target_path" ]]; then
        echo "Gemma SSH target file is missing: $target_path" >&2
        echo "Create it with one SSH alias, then set its mode to 600." >&2
        return 2
    fi
    if [[ ! -f "$target_path" || -L "$target_path" ]]; then
        echo "Gemma SSH target must be a regular non-symlink file: $target_path" >&2
        return 2
    fi

    if ! read -r owner_uid mode size < <(stat -c '%u %a %s' "$target_path"); then
        echo "Could not inspect the Gemma SSH target file: $target_path" >&2
        return 2
    fi
    if [[ "$owner_uid" != "$(id -u)" ]]; then
        echo "Gemma SSH target file must be owned by the current user: $target_path" >&2
        return 2
    fi
    if [[ "$mode" != "600" ]]; then
        echo "Gemma SSH target file must have mode 600: $target_path" >&2
        return 2
    fi
    if [[ ! "$size" =~ ^[0-9]+$ ]] || ((size == 0 || size > 256)); then
        echo "Gemma SSH target file must contain one alias of 1 to 255 characters." >&2
        return 2
    fi

    mapfile -t target_lines <"$target_path"
    if ((${#target_lines[@]} != 1)); then
        echo "Gemma SSH target file must contain exactly one non-empty line." >&2
        return 2
    fi
    target="${target_lines[0]}"
    if ((${#target} == 0 || ${#target} > 255)); then
        echo "Gemma SSH target file must contain one alias of 1 to 255 characters." >&2
        return 2
    fi
    # The allowlist excludes whitespace and leading SSH options. User names,
    # ports, and other connection details belong in ~/.ssh/config.
    if [[ ! "$target" =~ ^[A-Za-z0-9._-]+$ ]]; then
        echo "Gemma SSH target must use only ASCII letters, digits, '.', '_', or '-'." >&2
        echo "Configure user names and ports in ~/.ssh/config." >&2
        return 2
    fi
    if [[ "$target" == -* ]]; then
        echo "Gemma SSH target must not begin with '-'." >&2
        return 2
    fi

    printf '%s\n' "$target"
}
