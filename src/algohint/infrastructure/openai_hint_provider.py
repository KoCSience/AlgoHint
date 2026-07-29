"""OpenAI Responses API adapter for GPT-5.6 tutoring hints."""

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


class OpenAIHintProvider:
    """Call GPT-5.6 without tools, storage, or access to private judge assets."""

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

        configured = bool(os.environ.get("OPENAI_API_KEY"))
        return ProviderAvailability(
            available=configured,
            reason=None if configured else "OPENAI_API_KEYが設定されていません。",
            sends_data_off_device=True,
        )

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory()
        from openai import OpenAI

        return OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            timeout=self._timeout_seconds,
            max_retries=1,
        )

    def generate(self, request: HintGenerationRequest) -> GeneratedHint:
        """Request one strict JSON hint and discard the raw provider response."""

        try:
            response = self._client().responses.create(
                model=self._model,
                instructions=SYSTEM_INSTRUCTIONS,
                input=build_hint_prompt(request),
                reasoning={"effort": "low"},
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "algohint_response",
                        "schema": ProviderHintPayload.model_json_schema(),
                        "strict": True,
                    },
                    "verbosity": "low",
                },
                max_output_tokens=600,
                safety_identifier=request.learner_key,
                store=False,
            )
            payload = ProviderHintPayload.model_validate_json(response.output_text)
        except Exception as error:
            raise HintProviderError("openai_request_failed") from error
        return GeneratedHint(
            text=payload.text,
            category=payload.category,
            provider="openai",
            model_name=self._model,
        )
