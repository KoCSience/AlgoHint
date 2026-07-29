"""OpenAI-compatible vLLM and llama.cpp adapter for external Gemma servers."""

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from pydantic import ValidationError

from algohint.domain.enums import (
    GemmaBackend,
    GemmaDeployment,
    ProviderFailureReason,
)
from algohint.domain.errors import HintProviderError
from algohint.domain.models import (
    GeneratedHint,
    HintGenerationRequest,
    ProviderAvailability,
    ProviderDiagnostic,
)
from algohint.infrastructure.gemma_endpoint import gemma_endpoint_availability
from algohint.infrastructure.hint_prompt import (
    SYSTEM_INSTRUCTIONS,
    ProviderHintPayload,
    build_hint_prompt,
)

LOGGER = logging.getLogger(__name__)


class GemmaHintProvider:
    """Call a separately managed local model server to keep app memory bounded."""

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        backend: GemmaBackend = GemmaBackend.VLLM,
        deployment: GemmaDeployment = GemmaDeployment.AUTO,
        timeout_seconds: float = 120.0,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._backend = backend
        self._deployment = deployment
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory

    def availability(self) -> ProviderAvailability:
        """Apply explicit deployment policy, including SSH-tunneled remote servers."""

        return gemma_endpoint_availability(
            self._base_url,
            self._deployment,
        )

    def _create_client(self):
        if self._client_factory is not None:
            return self._client_factory()
        from openai import OpenAI

        return OpenAI(
            api_key=os.environ.get("ALGOHINT_GEMMA_API_KEY", "local-vllm"),
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            max_retries=1,
        )

    @contextmanager
    def _managed_client(self) -> Iterator[Any]:
        client = self._create_client()
        try:
            yield client
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as error:
                    LOGGER.warning(
                        "gemma_client_close_failed provider=gemma backend=%s "
                        "model=%s exception_type=%s",
                        self._backend.value,
                        self._model,
                        error.__class__.__name__,
                    )

    def generate(self, request: HintGenerationRequest) -> GeneratedHint:
        """Request JSON using the selected server's documented wire dialect."""

        try:
            with self._managed_client() as client:
                response = client.chat.completions.create(
                    **self._completion_arguments(request)
                )
                content = response.choices[0].message.content
            if not isinstance(content, str):
                raise ValueError("missing response content")
            payload = ProviderHintPayload.model_validate_json(content)
        except Exception as error:
            raise self._classified_error(error) from error
        return GeneratedHint(
            text=payload.text,
            category=payload.category,
            provider="gemma",
            model_name=self._model,
        )

    def _completion_arguments(self, request: HintGenerationRequest) -> dict[str, Any]:
        """Keep incompatible structured-output shapes out of transport code."""

        base: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": build_hint_prompt(request)},
            ],
        }
        schema = ProviderHintPayload.model_json_schema()
        if self._backend is GemmaBackend.LLAMA_CPP:
            return {
                **base,
                "max_tokens": 600,
                "response_format": {
                    "type": "json_schema",
                    "schema": schema,
                },
            }
        return {
            **base,
            "max_completion_tokens": 600,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "algohint_response",
                    "schema": schema,
                    "strict": True,
                },
            },
        }

    def diagnose(self, *, verbose: bool = False) -> ProviderDiagnostic:
        """Check model discovery without sending learner content."""

        if not self.availability().available:
            return ProviderDiagnostic(
                healthy=False,
                provider="gemma",
                model=self._model,
                reason_code=ProviderFailureReason.NOT_CONFIGURED,
            )
        try:
            with self._managed_client() as client:
                response = client.models.list()
                data = getattr(response, "data", response)
                model_ids = {getattr(item, "id", None) for item in data}
        except Exception as error:
            classified = self._classified_error(error)
            return ProviderDiagnostic(
                healthy=False,
                provider="gemma",
                model=self._model,
                reason_code=classified.reason_code,
                http_status=classified.http_status,
                retryable=classified.retryable,
                exception_type=classified.exception_type,
            )
        if self._model not in model_ids:
            return ProviderDiagnostic(
                healthy=False,
                provider="gemma",
                model=self._model,
                reason_code=ProviderFailureReason.MODEL_NOT_FOUND,
            )
        return ProviderDiagnostic(healthy=True, provider="gemma", model=self._model)

    def _classified_error(self, error: Exception) -> HintProviderError:
        from openai import APIConnectionError, APIStatusError, APITimeoutError

        if isinstance(error, APIStatusError):
            reason_code, retryable = self._classify_http_status(error.status_code)
            return HintProviderError(
                reason_code=reason_code,
                provider="gemma",
                model=self._model,
                http_status=error.status_code,
                retryable=retryable,
                exception_type=error.__class__.__name__,
            )
        if isinstance(error, (APITimeoutError, TimeoutError)):
            reason_code = ProviderFailureReason.TIMEOUT
            retryable = True
        elif isinstance(error, APIConnectionError):
            reason_code = ProviderFailureReason.PROVIDER_UNAVAILABLE
            retryable = True
        elif isinstance(error, (ValidationError, ValueError)):
            reason_code = ProviderFailureReason.INVALID_STRUCTURED_RESPONSE
            retryable = False
        elif isinstance(error, RuntimeError) and "client has been closed" in str(error).lower():
            reason_code = ProviderFailureReason.CLIENT_LIFECYCLE_ERROR
            retryable = False
        else:
            reason_code = ProviderFailureReason.UNKNOWN_PROVIDER_ERROR
            retryable = False
        return HintProviderError(
            reason_code=reason_code,
            provider="gemma",
            model=self._model,
            retryable=retryable,
            exception_type=error.__class__.__name__,
        )

    @staticmethod
    def _classify_http_status(
        status_code: int,
    ) -> tuple[ProviderFailureReason, bool]:
        if status_code in {400, 413, 422}:
            return ProviderFailureReason.INVALID_REQUEST, False
        if status_code in {401, 403}:
            return ProviderFailureReason.AUTHENTICATION_OR_PERMISSION, False
        if status_code == 404:
            return ProviderFailureReason.MODEL_NOT_FOUND, False
        if status_code in {408, 504}:
            return ProviderFailureReason.TIMEOUT, True
        if status_code == 429:
            return ProviderFailureReason.RATE_OR_QUOTA_EXCEEDED, True
        if status_code in {500, 502, 503}:
            return ProviderFailureReason.PROVIDER_UNAVAILABLE, True
        return ProviderFailureReason.UNKNOWN_PROVIDER_ERROR, False
