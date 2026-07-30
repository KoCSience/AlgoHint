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
    QuizRequest,
    QuizResponse,
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
from algohint_gemma_server.status import (
    RequestKind,
    RuntimeState,
    RuntimeStatusReporter,
)

LOGGER = logging.getLogger(__name__)
GENERATION_STATES: dict[RequestKind, RuntimeState] = {
    "hint": "generating_hint",
    "review": "generating_review",
    "quiz": "generating_quiz",
}


def create_app(
    *,
    config: ServerConfig | None = None,
    runtime_factory: Callable[[ServerConfig], HintRuntime] | None = None,
    status_reporter: RuntimeStatusReporter | None = None,
) -> FastAPI:
    """Build one service instance with injectable runtime ownership for tests."""

    resolved_config = config or ServerConfig.from_environment()
    reporter = status_reporter or RuntimeStatusReporter.from_environment(
        model_id=resolved_config.model_id,
        revision=resolved_config.model_revision,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        reporter.update("starting")
        runtime = (
            runtime_factory(resolved_config)
            if runtime_factory is not None
            else TransformersGemmaRuntime(resolved_config, reporter)
        )
        app.state.runtime = runtime
        app.state.generation_lock = asyncio.Lock()
        try:
            if runtime_factory is not None:
                reporter.update("loading_processor")
            LOGGER.info(
                "gemma_processor_load_start provider=gemma backend=transformers "
                "model=%s revision=%s",
                resolved_config.model_id,
                resolved_config.model_revision,
            )
            await asyncio.to_thread(runtime.load)
        except BaseException as error:
            reporter.update("failed", exception_type=error.__class__.__name__)
            LOGGER.error(
                "gemma_model_load_failed provider=gemma backend=transformers "
                "model=%s revision=%s exception_type=%s",
                resolved_config.model_id,
                resolved_config.model_revision,
                error.__class__.__name__,
            )
            raise
        reporter.update("ready")
        LOGGER.info(
            "gemma_model_ready provider=gemma backend=transformers model=%s revision=%s",
            resolved_config.model_id,
            resolved_config.model_revision,
        )
        try:
            yield
        finally:
            reporter.update("stopping")
            LOGGER.info(
                "gemma_server_stopping provider=gemma backend=transformers model=%s",
                resolved_config.model_id,
            )
            reporter.update("stopped")
            LOGGER.info(
                "gemma_server_stopped provider=gemma backend=transformers model=%s",
                resolved_config.model_id,
            )

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

    async def generate_text(
        *,
        request_kind: RequestKind,
        system_instructions: str,
        learner_context: str,
        max_output_chars: int,
        max_new_tokens: int,
    ) -> str:
        """Run one request while exposing only safe state and log metadata."""

        runtime: HintRuntime = app.state.runtime
        if not runtime.ready:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        generation_lock: asyncio.Lock = app.state.generation_lock
        if generation_lock.locked():
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        reporter.update(GENERATION_STATES[request_kind], request_kind=request_kind)
        LOGGER.info(
            "gemma_generation_start provider=gemma backend=transformers "
            "model=%s request_kind=%s request_id=%s",
            resolved_config.model_id,
            request_kind,
            request_id,
        )
        try:
            async with generation_lock:
                text = await asyncio.to_thread(
                    runtime.generate,
                    system_instructions,
                    learner_context,
                    max_output_chars=max_output_chars,
                    max_new_tokens=max_new_tokens,
                )
        except InputTooLongError as error:
            _report_generation_error(
                reporter,
                request_kind,
                started,
                error,
                model_id=resolved_config.model_id,
                request_id=request_id,
            )
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE) from error
        except InvalidModelOutputError as error:
            _report_generation_error(
                reporter,
                request_kind,
                started,
                error,
                model_id=resolved_config.model_id,
                request_id=request_id,
            )
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY) from error
        except ModelNotReadyError as error:
            _report_generation_error(
                reporter,
                request_kind,
                started,
                error,
                model_id=resolved_config.model_id,
                request_id=request_id,
            )
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error
        except (RuntimeError, MemoryError) as error:
            _report_generation_error(
                reporter,
                request_kind,
                started,
                error,
                model_id=resolved_config.model_id,
                request_id=request_id,
            )
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error
        elapsed_ms = int((time.monotonic() - started) * 1_000)
        reporter.update(
            "ready",
            request_kind=request_kind,
            elapsed_ms=elapsed_ms,
        )
        LOGGER.info(
            "gemma_inference_complete provider=gemma backend=transformers "
            "model=%s request_kind=%s request_id=%s elapsed_ms=%d",
            resolved_config.model_id,
            request_kind,
            request_id,
            elapsed_ms,
        )
        return text

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
        text = await generate_text(
            request_kind="hint",
            system_instructions=hint_request.system_instructions,
            learner_context=hint_request.learner_context,
            max_output_chars=1_200,
            max_new_tokens=resolved_config.max_new_tokens,
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
        text = await generate_text(
            request_kind="review",
            system_instructions=review_request.system_instructions,
            learner_context=review_request.learner_context,
            max_output_chars=4_000,
            max_new_tokens=resolved_config.review_max_new_tokens,
        )
        return ReviewResponse(model=resolved_config.model_id, text=text)

    @app.post("/v1/quizzes", response_model=QuizResponse)
    async def quizzes(
        quiz_request: QuizRequest,
        authorization: str | None = Header(default=None),
    ) -> QuizResponse:
        """Generate bounded personalized-quiz JSON under the shared generation lock."""

        authorize(authorization)
        if quiz_request.model != resolved_config.model_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        text = await generate_text(
            request_kind="quiz",
            system_instructions=quiz_request.system_instructions,
            learner_context=quiz_request.learner_context,
            max_output_chars=8_000,
            max_new_tokens=resolved_config.quiz_max_new_tokens,
        )
        return QuizResponse(model=resolved_config.model_id, text=text)

    return app


def _report_generation_error(
    reporter: RuntimeStatusReporter,
    request_kind: RequestKind,
    started: float,
    error: Exception,
    *,
    model_id: str,
    request_id: str,
) -> None:
    """Record only the safe error class and elapsed time after request failure."""

    reporter.update(
        "ready_with_last_error",
        request_kind=request_kind,
        elapsed_ms=int((time.monotonic() - started) * 1_000),
        exception_type=error.__class__.__name__,
    )
    LOGGER.error(
        "gemma_generation_failed provider=gemma backend=transformers "
        "model=%s request_kind=%s request_id=%s exception_type=%s",
        model_id,
        request_kind,
        request_id,
        error.__class__.__name__,
    )
