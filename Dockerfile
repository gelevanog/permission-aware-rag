# syntax=docker/dockerfile:1

# ---- build: resolve dependencies with uv into a self-contained virtualenv ----
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---- runtime: slim image, non-root user ----
FROM python:3.12-slim
RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app data ./data
COPY --chown=app:app configs ./configs
COPY --chown=app:app results ./results

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CLEARANCE_MODEL_CACHE_DIR=/home/app/.cache/models \
    CLEARANCE_DEV_IDP_KEY_FILE=/home/app/.cache/dev-idp/signing-key.pem \
    LOG_FORMAT=json

USER app
# Volume mount points must exist (owned by the app user) before Docker initializes named volumes.
RUN mkdir -p /home/app/.cache/models /home/app/.cache/dev-idp

# The embedding model (BAAI/bge-small-en-v1.5, ~67 MB ONNX) is downloaded on first start into the models volume.
# BAKE_MODELS=true downloads it at build time instead, for air-gapped deployments.
ARG BAKE_MODELS=false
RUN if [ "$BAKE_MODELS" = "true" ]; then \
      python -c "from clearance.embeddings import FastEmbedEmbedder; from pathlib import Path; FastEmbedEmbedder('BAAI/bge-small-en-v1.5', Path('/home/app/.cache/models')).embed_query('warm up')"; \
    fi

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=300s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
CMD ["uvicorn", "clearance.api.app:create_default_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
