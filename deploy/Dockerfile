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

COPY pyproject.toml README.md /app/
COPY ics_mcp /app/ics_mcp
RUN pip install --upgrade pip \
    && pip install --prefix=/install /app

# ---------- prod ----------
FROM base AS prod

COPY --from=builder /install /usr/local
COPY --from=builder /app /app

USER mcp
EXPOSE 8765

ENV ICS_MCP_TRANSPORT=http \
    ICS_MCP_HTTP_HOST=0.0.0.0 \
    ICS_MCP_HTTP_PORT=8765

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8765/health || exit 1

ENTRYPOINT ["python", "-m", "ics_mcp"]
