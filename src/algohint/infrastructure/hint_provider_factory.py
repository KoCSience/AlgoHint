"""Composition helper for optional adaptive hint providers."""

from algohint.application.config import AppConfig
from algohint.domain.enums import GemmaBackend, HintProviderId
from algohint.domain.ports import LearningProvider
from algohint.infrastructure.gemma_hint_provider import GemmaHintProvider
from algohint.infrastructure.gemini_hint_provider import GeminiHintProvider
from algohint.infrastructure.openai_hint_provider import OpenAIHintProvider
from algohint.infrastructure.transformers_http_hint_provider import (
    TransformersHttpHintProvider,
)


def build_gemma_provider(config: AppConfig) -> LearningProvider:
    """Select an explicit Gemma wire contract instead of guessing server behavior."""

    if config.gemma_backend is GemmaBackend.TRANSFORMERS_HTTP:
        return TransformersHttpHintProvider(
            config.gemma_model,
            config.gemma_base_url,
            deployment=config.gemma_deployment,
            timeout_seconds=config.local_timeout_seconds,
            development_mode=config.development_mode,
        )
    return GemmaHintProvider(
        config.gemma_model,
        config.gemma_base_url,
        backend=config.gemma_backend,
        deployment=config.gemma_deployment,
        timeout_seconds=config.local_timeout_seconds,
    )


def build_hint_providers(config: AppConfig) -> dict[HintProviderId, LearningProvider]:
    """Create lazy adapters without reading keys or opening network connections."""

    return {
        HintProviderId.OPENAI: OpenAIHintProvider(
            config.openai_model,
            timeout_seconds=config.cloud_timeout_seconds,
        ),
        HintProviderId.GEMMA: build_gemma_provider(config),
        HintProviderId.GEMINI: GeminiHintProvider(
            config.gemini_model,
            timeout_seconds=config.cloud_timeout_seconds,
            development_mode=config.development_mode,
        ),
    }
