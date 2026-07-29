"""Environment-only server configuration with secret-safe representations."""

import math
import os
from dataclasses import dataclass, field


def _positive_int(name: str, default: int, *, maximum: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value <= 0 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


@dataclass(frozen=True)
class ServerConfig:
    """Validated operational settings; the API key is deliberately hidden from repr."""

    model_id: str = "google/gemma-4-12B"
    # Pin the verified public checkpoint so a server restart cannot silently
    # download a behaviorally different model from the moving main branch.
    model_revision: str = "023679ed352de9bb66cc873c9009ce3482585c08"
    api_key: str = field(default="", repr=False)
    max_input_tokens: int = 8_192
    max_new_tokens: int = 384
    gpu_memory_gib: int = 14
    cpu_memory_gib: int = 64
    request_max_bytes: int = 98_304

    @classmethod
    def from_environment(cls) -> "ServerConfig":
        """Read process variables without opening a credentials or dotenv file."""

        api_key = os.environ.get("ALGOHINT_GEMMA_API_KEY", "").strip()
        if len(api_key) < 32:
            raise ValueError("ALGOHINT_GEMMA_API_KEY must contain at least 32 characters")
        model_id = os.environ.get("ALGOHINT_GEMMA_MODEL", cls.model_id).strip()
        revision = os.environ.get("ALGOHINT_GEMMA_MODEL_REVISION", cls.model_revision).strip()
        if not model_id or not revision:
            raise ValueError("Gemma model and revision must not be empty")
        return cls(
            model_id=model_id,
            model_revision=revision,
            api_key=api_key,
            max_input_tokens=_positive_int(
                "ALGOHINT_GEMMA_MAX_INPUT_TOKENS", cls.max_input_tokens, maximum=65_536
            ),
            max_new_tokens=_positive_int(
                "ALGOHINT_GEMMA_MAX_NEW_TOKENS", cls.max_new_tokens, maximum=600
            ),
            gpu_memory_gib=_positive_int(
                "ALGOHINT_GEMMA_GPU_MEMORY_GIB", cls.gpu_memory_gib, maximum=128
            ),
            cpu_memory_gib=_positive_int(
                "ALGOHINT_GEMMA_CPU_MEMORY_GIB", cls.cpu_memory_gib, maximum=1_024
            ),
            request_max_bytes=_positive_int(
                "ALGOHINT_GEMMA_REQUEST_MAX_BYTES", cls.request_max_bytes, maximum=1_048_576
            ),
        )

    def max_memory(self, gpu_count: int) -> dict[int | str, str]:
        """Reserve device headroom instead of allowing model dispatch to fill every GPU."""

        if gpu_count <= 0:
            raise ValueError("at least one CUDA device is required")
        return {
            **{index: f"{self.gpu_memory_gib}GiB" for index in range(gpu_count)},
            "cpu": f"{self.cpu_memory_gib}GiB",
        }

    def validate_timeout(self, seconds: float) -> float:
        """Keep future timeout inputs finite if request cancellation is added."""

        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("timeout must be a positive finite number")
        return seconds
