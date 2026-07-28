#!/bin/sh

# Repair only the persisted virtual environment's ownership. Dev Containers
# remaps the non-root user to the host UID/GID, while an existing named volume
# keeps the numeric owner from the image that first initialized it.
set -eu

readonly expected_venv_dir="/workspace/.venv"
venv_dir="${UV_PROJECT_ENVIRONMENT:-}"

if [ "$venv_dir" != "$expected_venv_dir" ]; then
    echo "UV_PROJECT_ENVIRONMENT must be $expected_venv_dir (received: ${venv_dir:-unset})." >&2
    exit 64
fi

if [ ! -d "$venv_dir" ]; then
    echo "Virtual environment volume is not mounted at $venv_dir." >&2
    exit 66
fi

expected_owner="$(id -u):$(id -g)"
current_owner="$(stat --format='%u:%g' -- "$venv_dir")"

if [ "$current_owner" != "$expected_owner" ]; then
    echo "Repairing $venv_dir ownership: $current_owner -> $expected_owner"
    sudo /usr/bin/chown --recursive "$expected_owner" "$venv_dir"
else
    echo "Virtual environment ownership is already $expected_owner; skipping repair."
fi

exec uv sync --frozen
