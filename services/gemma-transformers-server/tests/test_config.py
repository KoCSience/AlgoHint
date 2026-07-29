"""Server settings fail closed without credentials or valid bounds."""

import pytest

from algohint_gemma_server.config import ServerConfig
from algohint_gemma_server.security import bearer_is_valid


def test_environment_config_hides_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "private-key-that-is-at-least-thirty-two-chars"
    monkeypatch.setenv("ALGOHINT_GEMMA_API_KEY", secret)
    monkeypatch.setenv("ALGOHINT_GEMMA_MODEL_REVISION", "pinned-revision")

    config = ServerConfig.from_environment()

    assert config.api_key == secret
    assert secret not in repr(config)
    assert config.model_revision == "pinned-revision"


def test_environment_config_requires_a_real_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALGOHINT_GEMMA_API_KEY", raising=False)

    with pytest.raises(ValueError, match="ALGOHINT_GEMMA_API_KEY"):
        ServerConfig.from_environment()


def test_bearer_authentication_is_strict() -> None:
    key = "a" * 32

    assert bearer_is_valid(f"Bearer {key}", key)
    assert not bearer_is_valid(f"bearer {key}", key)
    assert not bearer_is_valid(key, key)
    assert not bearer_is_valid(None, key)

