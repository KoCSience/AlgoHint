"""Atomic JSON writer shared by local persistence adapters."""

import json
import os
import tempfile
from pathlib import Path


def write_json_atomic(path: Path, payload: object) -> None:
    """Replace one JSON file atomically and keep restrictive temporary permissions."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
