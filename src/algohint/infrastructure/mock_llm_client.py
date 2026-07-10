"""Test double for a future external hint provider."""

from algohint.domain.models import LLMRequest, LLMResponse


class MockLLMClient:
    """Return a fixed response so tests never require a model or credentials."""

    def generate(self, _: LLMRequest) -> LLMResponse:
        """Produce a typed fixed response without network access or credentials."""

        return LLMResponse(text="テスト用の安全なヒントです。", provider="mock")
