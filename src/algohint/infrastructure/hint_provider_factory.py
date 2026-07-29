"""Composition helper for optional adaptive hint providers."""

from algohint.application.config import AppConfig
from algohint.domain.enums import HintProviderId
from algohint.domain.ports import HintProvider
from algohint.infrastructure.gemma_hint_provider import GemmaHintProvider
from algohint.infrastructure.gemini_hint_provider import GeminiHintProvider
from algohint.infrastructure.openai_hint_provider import OpenAIHintProvider


def build_hint_providers(config: AppConfig) -> dict[HintProviderId, HintProvider]:
    """Create lazy adapters without reading keys or opening network connections."""

    return {
        HintProviderId.OPENAI: OpenAIHintProvider(
            config.openai_model,
            timeout_seconds=config.cloud_timeout_seconds,
        ),
        HintProviderId.GEMMA: GemmaHintProvider(
            config.gemma_model,
            config.gemma_base_url,
            timeout_seconds=config.local_timeout_seconds,
        ),
        HintProviderId.GEMINI: GeminiHintProvider(
            config.gemini_model,
            timeout_seconds=config.cloud_timeout_seconds,
        ),
    }
