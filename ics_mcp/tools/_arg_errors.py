"""Argument validation errors in the shape of every other tool error. FastMCP
validates arguments before the tool body runs, so `map_ics_errors` never sees
them; this middleware turns pydantic's error, which FastMCP wraps in its own
`ValidationError`, into `invalid_argument` with
`field` and, for enums, the allowed values."""

from __future__ import annotations

import re
from typing import Any

import mcp.types as mt
from fastmcp.exceptions import ValidationError as FastMCPValidationError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from ics_mcp.errors import ICSError, raise_tool_error

_QUOTED = re.compile(r"'([^']*)'")


def _field(error: ErrorDetails) -> str:
    return ".".join(str(part) for part in error["loc"]) or "arguments"


def _allowed(error: ErrorDetails) -> list[str]:
    """Allowed values of an enum (`literal_error`, `enum`), else empty."""
    if error["type"] not in ("literal_error", "enum"):
        return []
    return _QUOTED.findall(str((error.get("ctx") or {}).get("expected", "")))


def _message(error: ErrorDetails) -> str:
    field = _field(error)
    kind = error["type"]
    if kind == "missing" or kind == "missing_argument":
        return f"Missing required argument `{field}`."
    if kind in ("extra_forbidden", "unexpected_keyword_argument"):
        return f"Unknown argument `{field}`."
    value = error.get("input")
    shown = repr(value) if isinstance(value, str | int | float | bool) else type(value).__name__
    allowed = _allowed(error)
    if allowed:
        return f"Invalid `{field}` ({shown}); allowed: {', '.join(allowed)}."
    return f"Invalid `{field}` ({shown}): {error['msg']}."


def argument_error(exc: ValidationError) -> ICSError:
    """`invalid_argument` for the first failed argument; the others, if any,
    are listed in `data.errors`."""
    errors = exc.errors(include_url=False)
    first = errors[0]
    allowed = _allowed(first)
    data: dict[str, Any] = {}
    if allowed:
        data["allowed"] = allowed
    if len(errors) > 1:
        data["errors"] = [{"field": _field(e), "message": _message(e)} for e in errors[1:]]
    return ICSError(
        "invalid_argument",
        _message(first),
        field=_field(first),
        data=data,
    )


class ArgumentErrors(Middleware):
    """Maps a pydantic validation error of the tool arguments to a tool error."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            return await call_next(context)
        except FastMCPValidationError as exc:
            if not isinstance(exc.__cause__, ValidationError):
                raise
            raise_tool_error(argument_error(exc.__cause__))
