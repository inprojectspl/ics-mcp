"""Structured errors: a machine-readable `code`, a `message` and an optional fix
`hint`. They reach the client as a `ToolError` (`isError: true`) with the
payload encoded as JSON in the message, so clients can parse it even when
FastMCP does not expose metadata fields."""

from __future__ import annotations

import json
from typing import Any, NoReturn

from fastmcp.exceptions import ToolError


class ICSError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        status: int | None = None,
        field: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.hint = hint
        self.status = status
        self.field = field
        self.data = data or {}
        super().__init__(message)

    def to_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.hint:
            out["hint"] = self.hint
        if self.status:
            out["status"] = self.status
        if self.field:
            out["field"] = self.field
        if self.data:
            out["data"] = self.data
        return out


def raise_tool_error(err: ICSError | str, *, code: str = "internal_error") -> NoReturn:
    """Re-raise as a fastmcp ToolError. Message is a JSON-encoded
    structured payload so clients can parse error code + hint without
    relying on FastMCP-version-specific kwargs."""
    if isinstance(err, str):
        err = ICSError(code, err)
    raise ToolError(json.dumps(err.to_payload(), ensure_ascii=False))
