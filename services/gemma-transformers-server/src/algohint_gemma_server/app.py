"""Authenticated FastAPI boundary for the private Gemma runtime."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from algohint_gemma_server.config import ServerConfig
from algohint_gemma_server.contracts import (
    HealthResponse,
    HintRequest,
    HintResponse,
    ModelInfo,
    ModelsResponse,
    ReviewRequest,
    ReviewResponse,
)
from algohint_gemma_server.model_runtime import (
    HintRuntime,
    InputTooLongError,
    InvalidModelOutputError,
    ModelNotReadyError,
    TransformersGemmaRuntime,
)
from algohint_gemma_server.security import bearer_is_valid

LOGGER = logging.getLogger(__name__)


def create_app(
    *,
    config: ServerConfig | None = None,
    runtime_factory: Callable[[ServerConfig], HintRuntime] | None = None,
) -> FastAPI:
    """Build one service instance with injectable runtime ownership for tests."""

    resolved_config = config or ServerConfig.from_environment()
    resolved_factory = runtime_factory or TransformersGemmaRuntime

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = resolved_factory(resolved_config)
        app.state.runtime = runtime
        app.state.generation_lock = asyncio.Lock()
        await asyncio.to_thread(runtime.load)
        LOGGER.info(
            "gemma_model_ready provider=gemma backend=transformers model=%s revision=%s",
            resolved_config.model_id,
            resolved_config.model_revision,
        )
        yield

    app = FastAPI(
        title="AlgoHint Gemma Server",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def reject_large_declared_bodies(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": "Bad Request"},
                )
            if size > resolved_config.request_max_bytes:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "Content Too Large"},
                )
        return await call_next(request)

    def authorize(authorization: str | None) -> None:
        if not bearer_is_valid(authorization, resolved_config.api_key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        runtime: HintRuntime = app.state.runtime
        return HealthResponse(status="ok" if runtime.ready else "loading", ready=runtime.ready)

    @app.get("/v1/models", response_model=ModelsResponse)
    async def models(authorization: str | None = Header(default=None)) -> ModelsResponse:
        authorize(authorization)
        runtime: HintRuntime = app.state.runtime
        return ModelsResponse(
            data=(
                ModelInfo(
                    id=resolved_config.model_id,
                    revision=resolved_config.model_revision,
                    ready=runtime.ready,
                ),
            )
        )

    @app.post("/v1/hints", response_model=HintResponse)
    async def hints(
        hint_request: HintRequest,
        authorization: str | None = Header(default=None),
    ) -> HintResponse:
        authorize(authorization)
        if hint_request.model != resolved_config.model_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        runtime: HintRuntime = app.state.runtime
        if not runtime.ready:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        generation_lock: asyncio.Lock = app.state.generation_lock
        if generation_lock.locked():
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        try:
            async with generation_lock:
                text = await asyncio.to_thread(
                    runtime.generate,
                    hint_request.system_instructions,
                    hint_request.learner_context,
                    max_output_chars=1_200,
                )
        except InputTooLongError as error:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE) from error
        except InvalidModelOutputError as error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY) from error
        except ModelNotReadyError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error
        except (RuntimeError, MemoryError) as error:
            LOGGER.error(
                "gemma_inference_failed provider=gemma backend=transformers "
                "model=%s request_id=%s exception_type=%s",
                resolved_config.model_id,
                request_id,
                error.__class__.__name__,
            )
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error
        LOGGER.info(
            "gemma_inference_complete provider=gemma backend=transformers "
            "model=%s request_id=%s elapsed_ms=%d",
            resolved_config.model_id,
            request_id,
            int((time.monotonic() - started) * 1_000),
        )
        return HintResponse(model=resolved_config.model_id, text=text)

    @app.post("/v1/reviews", response_model=ReviewResponse)
    async def reviews(
        review_request: ReviewRequest,
        authorization: str | None = Header(default=None),
    ) -> ReviewResponse:
        """Generate bounded review JSON without accepting arbitrary options."""

        authorize(authorization)
        if review_request.model != resolved_config.model_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        runtime: HintRuntime = app.state.runtime
        if not runtime.ready:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        generation_lock: asyncio.Lock = app.state.generation_lock
        if generation_lock.locked():
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        try:
            async with generation_lock:
                text = await asyncio.to_thread(
                    runtime.generate,
                    review_request.system_instructions,
                    review_request.learner_context,
                    max_output_chars=4_000,
                )
        except InputTooLongError as error:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE) from error
        except InvalidModelOutputError as error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY) from error
        except ModelNotReadyError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error
        except (RuntimeError, MemoryError) as error:
            LOGGER.error(
                "gemma_review_failed provider=gemma backend=transformers "
                "model=%s request_id=%s exception_type=%s",
                resolved_config.model_id,
                request_id,
                error.__class__.__name__,
            )
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error
        LOGGER.info(
            "gemma_review_complete provider=gemma backend=transformers "
            "model=%s request_id=%s elapsed_ms=%d",
            resolved_config.model_id,
            request_id,
            int((time.monotonic() - started) * 1_000),
        )
        return ReviewResponse(model=resolved_config.model_id, text=text)

    return app
