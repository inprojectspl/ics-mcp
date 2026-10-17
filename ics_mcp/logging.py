"""Structured logging, always to stderr: stdio MCP reserves stdout for JSON-RPC
(spec §basic/transports/stdio)."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )
    # httpx and httpcore log every request line at INFO, including the URL,
    # and share tokens travel in the path (/api/share/{token}/...).
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(max(log_level, logging.WARNING))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "ics_mcp") -> Any:
    return structlog.get_logger(name)
