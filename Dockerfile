# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.7

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS base

COPY --from=uv /uv /uvx /usr/local/bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/algohint/.venv

# A fixed identity keeps runtime privileges predictable and lets named volumes
# inherit ownership without granting the application root access.
RUN groupadd --gid 10001 algohint \
    && useradd --uid 10001 --gid algohint --create-home --shell /bin/bash algohint \
    && mkdir --parents /opt/algohint \
    && chown algohint:algohint /opt/algohint

WORKDIR /opt/algohint

FROM base AS development

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir --parents /workspace/.venv \
    && chown --recursive algohint:algohint /workspace

WORKDIR /workspace
USER algohint

CMD ["sleep", "infinity"]

FROM base AS builder

WORKDIR /opt/algohint
COPY --chown=algohint:algohint pyproject.toml uv.lock README.md ./
COPY --chown=algohint:algohint src/ src/

USER algohint
RUN uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime

ENV HOME=/tmp \
    PATH=/opt/algohint/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GRADIO_ANALYTICS_ENABLED=False

RUN groupadd --gid 10001 algohint \
    && useradd --uid 10001 --gid algohint --no-create-home --shell /usr/sbin/nologin algohint

WORKDIR /opt/algohint
COPY --from=builder --chown=algohint:algohint /opt/algohint/.venv .venv
COPY --chown=algohint:algohint data/ data/

# Only data/runtime is intended to be writable. The rest of the image can be
# mounted read-only while judge scratch files live in a size-limited /tmp.
VOLUME ["/opt/algohint/data/runtime"]

USER algohint
EXPOSE 7860

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/', timeout=2)"]

ENTRYPOINT ["algohint"]
CMD ["--host", "0.0.0.0", "--port", "7860", "--data-dir", "/opt/algohint/data"]
