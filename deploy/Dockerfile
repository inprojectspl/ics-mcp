# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r mcp && useradd -r -g mcp -d /home/mcp -m mcp

WORKDIR /app

# ---------- builder ----------
FROM base AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

# The image installs exactly the locked set CI tested (`uv sync --frozen`).
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml uv.lock README.md /app/
RUN uv sync --frozen --no-dev --no-install-project
COPY ics_mcp /app/ics_mcp
RUN uv sync --frozen --no-dev --no-editable

# ---------- prod ----------
FROM base AS prod

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

USER mcp
EXPOSE 8765

ENV ICS_MCP_TRANSPORT=http \
    ICS_MCP_HTTP_HOST=0.0.0.0 \
    ICS_MCP_HTTP_PORT=8765

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8765/health || exit 1

ENTRYPOINT ["python", "-m", "ics_mcp"]
