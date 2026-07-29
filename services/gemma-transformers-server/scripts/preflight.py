"""Read-only validation for the restricted three-GPU deployment host."""

from __future__ import annotations

import socket


def main() -> None:
    """Fail before model download when CUDA, BF16, or the private port is unavailable."""

    import torch

    if not torch.cuda.is_available():
        raise SystemExit("preflight failed: CUDA is unavailable")
    if torch.cuda.device_count() < 3:
        raise SystemExit("preflight failed: three visible GPUs are required")
    if not torch.cuda.is_bf16_supported():
        print("preflight warning: BF16 unsupported; the server will use FP16")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 18080))
        except OSError as error:
            raise SystemExit("preflight failed: 127.0.0.1:18080 is unavailable") from error
    for index in range(torch.cuda.device_count()):
        properties = torch.cuda.get_device_properties(index)
        print(
            "gpu_ready "
            f"index={index} name={properties.name!r} "
            f"memory_mib={properties.total_memory // (1024 * 1024)}"
        )


if __name__ == "__main__":
    main()

