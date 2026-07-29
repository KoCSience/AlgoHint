"""OpenAI-compatible vLLM adapter for an external Gemma 4 12B server."""

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

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


class GemmaHintProvider:
    """Call a separately managed local model server to keep app memory bounded."""

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        timeout_seconds: float = 120.0,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory

    def availability(self) -> ProviderAvailability:
        """Classify loopback separately so remote Gemma endpoints require consent."""

        parsed = urlparse(self._base_url)
        configured = parsed.scheme in {"http", "https"} and parsed.hostname is not None
        loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        return ProviderAvailability(
            available=configured,
            reason=None if configured else "Gemmaの有効なHTTP接続先が設定されていません。",
            sends_data_off_device=configured and not loopback,
        )

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory()
        from openai import OpenAI

        return OpenAI(
            api_key=os.environ.get("ALGOHINT_GEMMA_API_KEY", "local-vllm"),
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            max_retries=1,
        )

    def generate(self, request: HintGenerationRequest) -> GeneratedHint:
        """Request a JSON hint from vLLM and validate it locally."""

        try:
            response = self._client().chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                    {"role": "user", "content": build_hint_prompt(request)},
                ],
                max_completion_tokens=600,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "algohint_response",
                        "schema": ProviderHintPayload.model_json_schema(),
                        "strict": True,
                    },
                },
            )
            content = response.choices[0].message.content
            if not isinstance(content, str):
                raise ValueError("missing response content")
            payload = ProviderHintPayload.model_validate_json(content)
        except Exception as error:
            raise HintProviderError("gemma_request_failed") from error
        return GeneratedHint(
            text=payload.text,
            category=payload.category,
            provider="gemma",
            model_name=self._model,
        )
