"""Google Gemini API adapter for structured tutoring hints."""

import os
from collections.abc import Callable
from typing import Any

from algohint.domain.errors import HintProviderError
from algohint.domain.models import (
    GeneratedHint,
    HintGenerationRequest,
    ProviderAvailability,
)
from algohint.infrastructure.hint_prompt import (
    SYSTEM_INSTRUCTIONS,
    ProviderHintPayload,
    build_hint_prompt,
)


class GeminiHintProvider:
    """Call Gemini with JSON output while keeping credentials environment-only."""

    def __init__(
        self,
        model: str,
        *,
        timeout_seconds: float = 45.0,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory

    def availability(self) -> ProviderAvailability:
        """Report configuration presence without exposing the credential value."""

        configured = bool(os.environ.get("GEMINI_API_KEY"))
        return ProviderAvailability(
            available=configured,
            reason=None if configured else "GEMINI_API_KEYが設定されていません。",
            sends_data_off_device=True,
        )

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory()
        from google import genai
        from google.genai import types

        return genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=int(self._timeout_seconds * 1_000)),
        )

    def generate(self, request: HintGenerationRequest) -> GeneratedHint:
        """Request one structured hint and normalize SDK failures."""

        try:
            response = self._client().models.generate_content(
                model=self._model,
                contents=build_hint_prompt(request),
                config={
                    "system_instruction": SYSTEM_INSTRUCTIONS,
                    "response_mime_type": "application/json",
                    "response_json_schema": ProviderHintPayload.model_json_schema(),
                    "max_output_tokens": 600,
                },
            )
            if not isinstance(response.text, str):
                raise ValueError("missing response text")
            payload = ProviderHintPayload.model_validate_json(response.text)
        except Exception as error:
            raise HintProviderError("gemini_request_failed") from error
        return GeneratedHint(
            text=payload.text,
            category=payload.category,
            provider="gemini",
            model_name=self._model,
        )
