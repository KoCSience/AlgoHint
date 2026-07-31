from dataclasses import asdict

import pytest

from algohint.application.config import AppConfig
from algohint.domain.enums import GemmaBackend, GemmaDeployment, HintProviderId


def test_config_reads_non_secret_preferences_from_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Development defaults may vary without making credentials application state."""

    monkeypatch.setenv("ALGOHINT_ENV", "development")
    monkeypatch.setenv("ALGOHINT_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("ALGOHINT_GEMINI_MODEL", "test-gemini")
    monkeypatch.setenv("ALGOHINT_GEMMA_BACKEND", "transformers_http")
    monkeypatch.setenv("ALGOHINT_GEMMA_DEPLOYMENT", "remote")
    monkeypatch.setenv("ALGOHINT_GEMMA_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-enter-config")

    config = AppConfig.from_environment()

    assert config.development_mode
    assert config.default_hint_provider is HintProviderId.GEMINI
    assert config.gemini_model == "test-gemini"
    assert config.gemma_backend is GemmaBackend.TRANSFORMERS_HTTP
    assert config.gemma_deployment is GemmaDeployment.REMOTE
    assert config.local_timeout_seconds == 600
    assert all("key" not in field_name for field_name in asdict(config))
    assert "must-not-enter-config" not in repr(config)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("ALGOHINT_ENV", "staging", "ALGOHINT_ENV"),
        ("ALGOHINT_LLM_PROVIDER", "unknown", "ALGOHINT_LLM_PROVIDER"),
        ("ALGOHINT_GEMMA_BACKEND", "unknown", "ALGOHINT_GEMMA_BACKEND"),
        ("ALGOHINT_GEMMA_DEPLOYMENT", "unknown", "ALGOHINT_GEMMA_DEPLOYMENT"),
        ("ALGOHINT_GEMMA_TIMEOUT_SECONDS", "0", "ALGOHINT_GEMMA_TIMEOUT_SECONDS"),
    ],
)
def test_config_rejects_invalid_environment_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    """Reject ambiguous deployment configuration before the UI starts."""

    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        AppConfig.from_environment()
