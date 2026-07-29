"""Google Gemini API adapter for structured tutoring hints."""

import os
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from algohint.domain.enums import ProviderFailureReason
from algohint.domain.errors import HintProviderError
from algohint.domain.models import (
    GeneratedHint,
    HintGenerationRequest,
    ProviderAvailability,
    ProviderDiagnostic,
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

        configured = bool(os.environ.get("GEMINI_API_KEY", "").strip())
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
            # AlgoHint's Gemini adapter intentionally uses the Developer API.
            # Explicit flags prevent ambient Vertex/Enterprise settings from
            # switching authentication to Google Cloud access tokens.
            api_key=os.environ["GEMINI_API_KEY"].strip(),
            vertexai=False,
            enterprise=False,
            http_options=types.HttpOptions(timeout=int(self._timeout_seconds * 1_000)),
        )

    def generate(self, request: HintGenerationRequest) -> GeneratedHint:
        """Request one structured hint and classify failures without raw content."""

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
        except Exception as error:
            raise self._classified_error(error) from error
        try:
            response_text = response.text
        except (AttributeError, ValueError) as error:
            raise self._response_error(
                ProviderFailureReason.EMPTY_OR_BLOCKED_RESPONSE, error
            ) from error
        if not isinstance(response_text, str) or not response_text.strip():
            empty_response_error = ValueError("empty provider response")
            raise self._response_error(
                ProviderFailureReason.EMPTY_OR_BLOCKED_RESPONSE,
                empty_response_error,
            ) from empty_response_error
        try:
            payload = ProviderHintPayload.model_validate_json(response_text)
        except (ValidationError, ValueError) as error:
            raise self._response_error(
                ProviderFailureReason.INVALID_STRUCTURED_RESPONSE, error
            ) from error
        return GeneratedHint(
            text=payload.text,
            category=payload.category,
            provider="gemini",
            model_name=self._model,
        )

    def diagnose(self) -> ProviderDiagnostic:
        """Check key, permission, and model reachability without learner content."""

        if not self.availability().available:
            return ProviderDiagnostic(
                healthy=False,
                provider="gemini",
                model=self._model,
                reason_code=ProviderFailureReason.NOT_CONFIGURED,
            )
        try:
            self._client().models.get(model=self._model)
        except Exception as error:
            classified = self._classified_error(error)
            return ProviderDiagnostic(
                healthy=False,
                provider=classified.provider,
                model=classified.model,
                reason_code=classified.reason_code,
                http_status=classified.http_status,
                retryable=classified.retryable,
                exception_type=classified.exception_type,
            )
        return ProviderDiagnostic(healthy=True, provider="gemini", model=self._model)

    def _response_error(
        self, reason_code: ProviderFailureReason, error: Exception
    ) -> HintProviderError:
        """Create safe metadata for a response that crossed the HTTP boundary."""

        return HintProviderError(
            reason_code=reason_code,
            provider="gemini",
            model=self._model,
            exception_type=error.__class__.__name__,
        )

    def _classified_error(self, error: Exception) -> HintProviderError:
        """Map SDK and transport errors without retaining messages or bodies."""

        from google.genai.errors import APIError

        if isinstance(error, APIError):
            status = error.code
            reason_code, retryable = self._classify_http_status(status)
            return HintProviderError(
                reason_code=reason_code,
                provider="gemini",
                model=self._model,
                http_status=status,
                retryable=retryable,
                exception_type=error.__class__.__name__,
            )
        if isinstance(error, TimeoutError) or "Timeout" in error.__class__.__name__:
            return HintProviderError(
                reason_code=ProviderFailureReason.TIMEOUT,
                provider="gemini",
                model=self._model,
                retryable=True,
                exception_type=error.__class__.__name__,
            )
        if isinstance(error, RuntimeError):
            message = str(error)
            if "Could not resolve API token from the environment" in message:
                reason_code = ProviderFailureReason.AUTHENTICATION_OR_PERMISSION
                retryable = False
            elif message.startswith("Operation ") and " timed out." in message:
                reason_code = ProviderFailureReason.TIMEOUT
                retryable = True
            else:
                reason_code = ProviderFailureReason.UNKNOWN_PROVIDER_ERROR
                retryable = False
            return HintProviderError(
                reason_code=reason_code,
                provider="gemini",
                model=self._model,
                retryable=retryable,
                exception_type=error.__class__.__name__,
            )
        return HintProviderError(
            reason_code=ProviderFailureReason.UNKNOWN_PROVIDER_ERROR,
            provider="gemini",
            model=self._model,
            exception_type=error.__class__.__name__,
        )

    @staticmethod
    def _classify_http_status(status: int) -> tuple[ProviderFailureReason, bool]:
        """Classify retryability once so UI and diagnostics cannot disagree."""

        if status == 400:
            return ProviderFailureReason.INVALID_REQUEST, False
        if status in {401, 403}:
            return ProviderFailureReason.AUTHENTICATION_OR_PERMISSION, False
        if status == 404:
            return ProviderFailureReason.MODEL_NOT_FOUND, False
        if status == 429:
            return ProviderFailureReason.RATE_OR_QUOTA_EXCEEDED, True
        if status in {408, 499, 504}:
            return ProviderFailureReason.TIMEOUT, True
        if 500 <= status <= 599:
            return ProviderFailureReason.PROVIDER_UNAVAILABLE, True
        return ProviderFailureReason.UNKNOWN_PROVIDER_ERROR, False
