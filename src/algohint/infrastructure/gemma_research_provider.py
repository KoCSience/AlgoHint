"""Authenticated client for Gemma Server's grounded Research API."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from algohint.domain.models import (
    ResearchProviderRequest,
    ResearchResult,
    ResearchUsage,
)
from algohint.domain.ports import ResearchProvider


class ResearchProviderError(RuntimeError):
    """Secret-free failure suitable for a static knowledge fallback."""

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


class GemmaResearchProvider(ResearchProvider):
    """Send only public problem context to the private Gemma Server."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory

    def usage(self) -> ResearchUsage:
        """Read local Exa budget state without triggering search."""

        payload = self._request("GET", "/research/usage")
        return ResearchUsage.model_validate(payload)

    def research(self, request: ResearchProviderRequest) -> ResearchResult:
        """Execute one bounded research run after domain-level consent validation."""

        payload = self._request(
            "POST",
            "/research",
            json=request.model_dump(mode="json"),
        )
        return ResearchResult.model_validate(payload)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
    ) -> object:
        if not self._base_url:
            raise ResearchProviderError("gemma_research_not_configured")
        try:
            with self._managed_client() as client:
                response = client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=self._headers(),
                    json=json,
                )
                response.raise_for_status()
                return response.json()
        except ResearchProviderError:
            raise
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            reason = (
                "research_budget_or_rate_limited"
                if status in {402, 429}
                else "research_authentication_failed"
                if status in {401, 403}
                else "research_unavailable"
            )
            raise ResearchProviderError(reason, status_code=status) from error
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise ResearchProviderError("research_unavailable") from error
        except (ValueError, TypeError) as error:
            raise ResearchProviderError("invalid_research_response") from error

    def _headers(self) -> dict[str, str]:
        key = os.environ.get("ALGOHINT_GEMMA_API_KEY", "").strip()
        if not key:
            raise ResearchProviderError("gemma_credential_missing")
        return {"Authorization": f"Bearer {key}"}

    def _create_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        return httpx.Client(
            timeout=self._timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )

    @contextmanager
    def _managed_client(self) -> Iterator[Any]:
        client = self._create_client()
        try:
            yield client
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
