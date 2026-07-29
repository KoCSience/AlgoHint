"""Validated process configuration assembled without reading dotenv files."""

import os
from dataclasses import dataclass

from algohint.domain.enums import HintProviderId


@dataclass(frozen=True)
class AppConfig:
    """Non-secret application defaults read from the launch environment."""

    development_mode: bool = False
    default_hint_provider: HintProviderId = HintProviderId.OPENAI
    openai_model: str = "gpt-5.6-sol"
    gemini_model: str = "gemini-3.6-flash"
    gemma_model: str = "google/gemma-4-12B-it"
    gemma_base_url: str = ""
    cloud_timeout_seconds: float = 45.0
    local_timeout_seconds: float = 120.0

    @classmethod
    def from_environment(cls, environment_override: str | None = None) -> "AppConfig":
        """Build config from OS variables, never by opening a secret-bearing file."""

        environment = environment_override or os.environ.get("ALGOHINT_ENV", "production")
        if environment not in {"production", "development"}:
            raise ValueError("ALGOHINT_ENV must be production or development")
        provider_name = os.environ.get("ALGOHINT_LLM_PROVIDER", HintProviderId.OPENAI)
        try:
            provider = HintProviderId(provider_name)
        except ValueError as error:
            choices = ", ".join(item.value for item in HintProviderId)
            raise ValueError(f"ALGOHINT_LLM_PROVIDER must be one of: {choices}") from error
        return cls(
            development_mode=environment == "development",
            default_hint_provider=provider,
            openai_model=os.environ.get("ALGOHINT_OPENAI_MODEL", "gpt-5.6-sol"),
            gemini_model=os.environ.get("ALGOHINT_GEMINI_MODEL", "gemini-3.6-flash"),
            gemma_model=os.environ.get("ALGOHINT_GEMMA_MODEL", "google/gemma-4-12B-it"),
            gemma_base_url=os.environ.get("ALGOHINT_GEMMA_BASE_URL", ""),
        )
