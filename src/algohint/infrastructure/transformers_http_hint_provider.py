"""Client for AlgoHint's minimal authenticated Transformers Gemma service."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from algohint.domain.enums import (
    GemmaDeployment,
    GemmaGenerationFailureCode,
    ProviderFailureReason,
)
from algohint.domain.errors import HintProviderError
from algohint.domain.models import (
    CodeReviewRequest,
    GeneratedCodeReview,
    GeneratedHint,
    GeneratedPersonalizedQuiz,
    HintGenerationRequest,
    PersonalizedQuizRequest,
    ProviderAvailability,
    ProviderDiagnostic,
)
from algohint.infrastructure.code_review_prompt import (
    CODE_REVIEW_INSTRUCTIONS,
    ProviderCodeReviewPayload,
    build_code_review_prompt,
)
from algohint.infrastructure.gemma_endpoint import gemma_endpoint_availability
from algohint.infrastructure.hint_prompt import SYSTEM_INSTRUCTIONS, build_hint_prompt
from algohint.infrastructure.provider_debug import format_provider_exception
from algohint.infrastructure.personalized_quiz_prompt import (
    PERSONALIZED_QUIZ_INSTRUCTIONS,
    ProviderPersonalizedQuizPayload,
    build_personalized_quiz_prompt,
)

LOGGER = logging.getLogger(__name__)
SINGLE_JSON_FENCE = re.compile(
    r"\A```(?:json)?[ \t]*\r?\n(?P<body>.*?)\r?\n```[ \t]*\Z",
    flags=re.IGNORECASE | re.DOTALL,
)


def _normalize_structured_json(text: str) -> str:
    """Remove one transport-only JSON fence while preserving strict validation.

    Gemma can wrap an otherwise valid JSON object in a Markdown fence despite
    being instructed not to. Only one complete document is unwrapped; prose,
    nested fences, and multiple documents remain invalid Pydantic input.
    """

    stripped = text.strip()
    match = SINGLE_JSON_FENCE.fullmatch(stripped)
    if match is None:
        return stripped
    body = match.group("body").strip()
    if "```" in body:
        return stripped
    return body


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _HintResponse(_ResponseModel):
    model: str
    text: str = Field(min_length=1, max_length=1_200)


class _ReviewResponse(_ResponseModel):
    model: str
    text: str = Field(min_length=1, max_length=4_000)


class _QuizResponse(_ResponseModel):
    model: str
    text: str = Field(min_length=1, max_length=8_000)


class _ModelInfo(_ResponseModel):
    id: str
    revision: str
    backend: str
    ready: bool


class _ModelsResponse(_ResponseModel):
    data: tuple[_ModelInfo, ...]


class _GenerationDiagnosticResponse(_ResponseModel):
    model: str
    ready: bool


class _GenerationErrorDetail(_ResponseModel):
    code: GemmaGenerationFailureCode
    retryable: bool
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class _GenerationErrorResponse(_ResponseModel):
    error: _GenerationErrorDetail


class TransformersHttpHintProvider:
    """Generate hints through a private server without emulating OpenAI APIs."""

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        deployment: GemmaDeployment,
        timeout_seconds: float = 600.0,
        client_factory: Callable[[], Any] | None = None,
        development_mode: bool = False,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._deployment = deployment
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory
        self._development_mode = development_mode

    def availability(self) -> ProviderAvailability:
        """Require both a valid endpoint and the independently managed API key."""

        return gemma_endpoint_availability(
            self._base_url,
            self._deployment,
            credential_required=True,
            credential_configured=bool(
                os.environ.get("ALGOHINT_GEMMA_API_KEY", "").strip()
            ),
        )

    def _create_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        return httpx.Client(
            timeout=self._timeout_seconds,
            follow_redirects=False,
            # The supported deployment uses an explicit SSH tunnel. Prevent
            # ambient proxy variables from receiving learner content.
            trust_env=False,
        )

    @contextmanager
    def _managed_client(self) -> Iterator[Any]:
        client = self._create_client()
        try:
            yield client
        finally:
            self._close_client(client)

    def _close_client(self, client: Any) -> None:
        close = getattr(client, "close", None)
        if not callable(close):
            return
        try:
            close()
        except Exception as error:
            LOGGER.warning(
                "gemma_client_close_failed provider=gemma backend=transformers_http "
                "model=%s exception_type=%s",
                self._model,
                error.__class__.__name__,
            )

    def _headers(self) -> dict[str, str]:
        key = os.environ.get("ALGOHINT_GEMMA_API_KEY", "").strip()
        if not key:
            raise HintProviderError(
                reason_code=ProviderFailureReason.NOT_CONFIGURED,
                provider="gemma",
                model=self._model,
                exception_type="MissingCredential",
            )
        return {"Authorization": f"Bearer {key}"}

    def generate(self, request: HintGenerationRequest) -> GeneratedHint:
        """Request plain text and attach the authored category on the trusted side."""

        try:
            with self._managed_client() as client:
                response = client.post(
                    f"{self._base_url}/hints",
                    headers=self._headers(),
                    json={
                        "model": self._model,
                        "system_instructions": SYSTEM_INSTRUCTIONS,
                        "learner_context": build_hint_prompt(request),
                    },
                )
                response.raise_for_status()
                payload = _HintResponse.model_validate(response.json())
        except HintProviderError:
            raise
        except Exception as error:
            self._log_development_exception("hints", error)
            raise self._classified_error(error) from error
        if payload.model != self._model:
            mismatch_error = ValueError("response model does not match configured model")
            raise self._response_error(
                ProviderFailureReason.INVALID_STRUCTURED_RESPONSE, mismatch_error
            ) from mismatch_error
        return GeneratedHint(
            text=payload.text,
            category=request.authored_hint.category,
            provider="gemma",
            model_name=payload.model,
        )

    def generate_review(self, request: CodeReviewRequest) -> GeneratedCodeReview:
        """Use the dedicated authenticated review endpoint and validate its JSON."""

        try:
            with self._managed_client() as client:
                response = client.post(
                    f"{self._base_url}/reviews",
                    headers=self._headers(),
                    json={
                        "model": self._model,
                        "system_instructions": CODE_REVIEW_INSTRUCTIONS,
                        "learner_context": build_code_review_prompt(request),
                    },
                )
                response.raise_for_status()
                response_payload = _ReviewResponse.model_validate(response.json())
            if response_payload.model != self._model:
                raise ValueError("response model does not match configured model")
            payload = ProviderCodeReviewPayload.model_validate_json(
                _normalize_structured_json(response_payload.text)
            )
        except HintProviderError:
            raise
        except Exception as error:
            self._log_development_exception("reviews", error)
            raise self._classified_error(error) from error
        return payload.to_generated(provider="gemma", model_name=self._model)

    def generate_quiz(
        self,
        request: PersonalizedQuizRequest,
    ) -> GeneratedPersonalizedQuiz:
        """Use the dedicated authenticated quiz endpoint and validate its JSON."""

        try:
            with self._managed_client() as client:
                response = client.post(
                    f"{self._base_url}/quizzes",
                    headers=self._headers(),
                    json={
                        "model": self._model,
                        "system_instructions": PERSONALIZED_QUIZ_INSTRUCTIONS,
                        "learner_context": build_personalized_quiz_prompt(request),
                    },
                )
                response.raise_for_status()
                response_payload = _QuizResponse.model_validate(response.json())
            if response_payload.model != self._model:
                raise ValueError("response model does not match configured model")
            payload = ProviderPersonalizedQuizPayload.model_validate_json(
                _normalize_structured_json(response_payload.text)
            )
            return payload.to_generated(
                provider="gemma",
                model_name=self._model,
                mode=request.mode,
            )
        except HintProviderError:
            raise
        except Exception as error:
            self._log_development_exception("quizzes", error)
            raise self._classified_error(error) from error

    def diagnose(
        self,
        *,
        verbose: bool = False,
        generation_probe: bool = False,
    ) -> ProviderDiagnostic:
        """Check the contract and optionally generate with server-owned text."""

        availability = self.availability()
        if not availability.available:
            return ProviderDiagnostic(
                healthy=False,
                provider="gemma",
                model=self._model,
                reason_code=ProviderFailureReason.NOT_CONFIGURED,
            )
        try:
            with self._managed_client() as client:
                response = client.get(
                    f"{self._base_url}/models",
                    headers=self._headers(),
                )
                response.raise_for_status()
                models = _ModelsResponse.model_validate(response.json())
                if generation_probe:
                    probe_response = client.post(
                        f"{self._base_url}/diagnostics/generation",
                        headers=self._headers(),
                        content=b"",
                    )
                    probe_response.raise_for_status()
                    probe = _GenerationDiagnosticResponse.model_validate(
                        probe_response.json()
                    )
        except Exception as error:
            classified = (
                error if isinstance(error, HintProviderError) else self._classified_error(error)
            )
            debug_details = self._development_details(error) if verbose else None
            return ProviderDiagnostic(
                healthy=False,
                provider=classified.provider,
                model=classified.model,
                reason_code=classified.reason_code,
                http_status=classified.http_status,
                retryable=classified.retryable,
                exception_type=classified.exception_type,
                provider_detail_code=classified.provider_detail_code,
                debug_details=debug_details,
            )
        matched = next((item for item in models.data if item.id == self._model), None)
        if matched is None:
            return ProviderDiagnostic(
                healthy=False,
                provider="gemma",
                model=self._model,
                reason_code=ProviderFailureReason.MODEL_NOT_FOUND,
            )
        if not matched.ready:
            return ProviderDiagnostic(
                healthy=False,
                provider="gemma",
                model=self._model,
                reason_code=ProviderFailureReason.PROVIDER_UNAVAILABLE,
                retryable=True,
            )
        if generation_probe and (not probe.ready or probe.model != self._model):
            return ProviderDiagnostic(
                healthy=False,
                provider="gemma",
                model=self._model,
                reason_code=ProviderFailureReason.INVALID_STRUCTURED_RESPONSE,
                provider_detail_code=(
                    GemmaGenerationFailureCode.RESPONSE_PARSING_FAILURE.value
                ),
            )
        return ProviderDiagnostic(healthy=True, provider="gemma", model=self._model)

    def _classified_error(self, error: Exception) -> HintProviderError:
        """Separate connection-path failures from HTTP service responses.

        A refused TCP connection or failed SSH forwarding needs operator action
        on the endpoint path. It must not be presented as an upstream 5xx that
        could reasonably recover by waiting.
        """

        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code
            reason_code, retryable = self._classify_http_status(status_code)
            provider_detail_code: str | None = None
            if status_code in {502, 503}:
                server_failure = self._validated_server_failure(error.response)
                provider_detail_code = server_failure.code.value
                retryable = server_failure.retryable
                if (
                    server_failure.code
                    is GemmaGenerationFailureCode.RESPONSE_PARSING_FAILURE
                ):
                    reason_code = ProviderFailureReason.INVALID_STRUCTURED_RESPONSE
            return HintProviderError(
                reason_code=reason_code,
                provider="gemma",
                model=self._model,
                http_status=status_code,
                retryable=retryable,
                exception_type=error.__class__.__name__,
                provider_detail_code=provider_detail_code,
            )
        if isinstance(error, (httpx.TimeoutException, TimeoutError)):
            return self._response_error(
                ProviderFailureReason.TIMEOUT,
                error,
                retryable=True,
            )
        if isinstance(error, httpx.ConnectError):
            return self._response_error(
                ProviderFailureReason.ENDPOINT_UNREACHABLE,
                error,
                retryable=True,
            )
        if isinstance(error, httpx.TransportError):
            return self._response_error(
                ProviderFailureReason.PROVIDER_UNAVAILABLE,
                error,
                retryable=True,
            )
        if isinstance(error, (ValidationError, ValueError)):
            return self._response_error(
                ProviderFailureReason.INVALID_STRUCTURED_RESPONSE,
                error,
            )
        if isinstance(error, RuntimeError) and "client has been closed" in str(error).lower():
            return self._response_error(
                ProviderFailureReason.CLIENT_LIFECYCLE_ERROR,
                error,
            )
        return self._response_error(ProviderFailureReason.UNKNOWN_PROVIDER_ERROR, error)

    @staticmethod
    def _validated_server_failure(
        response: httpx.Response,
    ) -> _GenerationErrorDetail:
        """Accept only the closed schema and discard every arbitrary body."""

        try:
            return _GenerationErrorResponse.model_validate(response.json()).error
        except (ValidationError, ValueError):
            return _GenerationErrorDetail(
                code=GemmaGenerationFailureCode.UNKNOWN_GENERATION_FAILURE,
                retryable=False,
                request_id="0" * 32,
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

    def _response_error(
        self,
        reason_code: ProviderFailureReason,
        error: Exception,
        *,
        retryable: bool = False,
    ) -> HintProviderError:
        return HintProviderError(
            reason_code=reason_code,
            provider="gemma",
            model=self._model,
            retryable=retryable,
            exception_type=error.__class__.__name__,
        )

    def _development_details(self, error: Exception) -> str | None:
        if not self._development_mode:
            return None
        return format_provider_exception(
            error,
            secrets=(os.environ.get("ALGOHINT_GEMMA_API_KEY", ""),),
        )

    def _log_development_exception(self, operation: str, error: Exception) -> None:
        details = self._development_details(error)
        if details is None:
            return
        LOGGER.error(
            "gemma_provider_exception provider=gemma backend=transformers_http "
            "model=%s operation=%s\n%s",
            self._model,
            operation,
            details,
        )
