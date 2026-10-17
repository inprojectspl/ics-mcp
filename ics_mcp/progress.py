"""Progress reporting for long-running tools, when the client sent a
`progressToken`. Throttled, so a 100-file bundle is not 100 notifications, and
dropped when the channel fails; it never blocks the tool."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastmcp import Context

from ics_mcp.logging import get_logger

log = get_logger(__name__)

# Minimum gap between `notifications/progress`; the final one on close always
# fires, so the client sees `progress == total`.
_THROTTLE_MS = 100


@asynccontextmanager
async def progress_scope(
    ctx: Context, *, total: int | None = None, message: str = ""
) -> AsyncIterator[Callable[..., Awaitable[None]]]:
    state: dict[str, float] = {"current": 0, "last_emit_ms": 0.0}

    async def _emit(message: str | None) -> None:
        try:
            await ctx.report_progress(progress=state["current"], total=total, message=message)
        except Exception as e:
            log.debug("progress dropped", error=str(e))

    async def tick(amount: int = 1, message: str | None = None) -> None:
        state["current"] += amount
        now = time.monotonic() * 1000
        if now - state["last_emit_ms"] < _THROTTLE_MS:
            return
        state["last_emit_ms"] = now
        await _emit(message)

    if message:
        try:
            await ctx.info(message)
        except Exception as e:
            log.debug("info dropped", error=str(e))
    yield tick
    # Reached only when the work inside the scope finished without raising,
    # so a failed upload is never reported as complete.
    if total is not None:
        try:
            await ctx.report_progress(progress=total, total=total, message="done")
        except Exception as e:
            log.debug("final progress dropped", error=str(e))
