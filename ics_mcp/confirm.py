"""Confirm flow for destructive tools: `yolo` executes, `confirm=True` executes
one call, `interactive` asks through MCP elicitation, `dry_run` returns a
preview without calling ICS."""

from __future__ import annotations

from typing import Any

from fastmcp import Context
from pydantic import BaseModel

from ics_mcp.config import ConfirmMode
from ics_mcp.errors import ICSError


class _ConfirmAnswer(BaseModel):
    confirm: bool = False


async def confirm_or_skip(
    ctx: Context,
    *,
    action: str,
    target: str,
    confirm: bool | None,
    mode: ConfirmMode,
) -> dict[str, Any] | None:
    """`None` when the caller should execute, or a preview dict to return as-is (dry
    run). Raises `ICSError` when the user declines or `confirm=False` is passed."""
    # Contract: argument > session mode (help_md/confirm.md). An explicit
    # `confirm=False` must refuse before the mode lets anything through:
    # yolo would run the operation against an explicit refusal, dry_run
    # would return a preview that looks like success.
    if confirm is False:
        raise ICSError(
            "confirm_required",
            f"{action} → {target}: explicitly refused (confirm=False).",
            hint="Set confirm=True or `ics_session_set_mode('yolo')`.",
        )
    if confirm is True or mode == "yolo":
        return None
    if mode == "dry_run":
        return {
            "action": action,
            "target": target,
            "note": "dry_run mode: the operation was not executed.",
        }
    try:
        result = await ctx.elicit(
            message=f"Confirm: {action} → {target}",
            # The dict shorthand {"confirm": (bool, False)} breaks in FastMCP 3
            # (read as an enum), so every prompt failed as "no elicitation".
            response_type=_ConfirmAnswer,  # type: ignore[arg-type]  # mypy only sees FastMCP's first overload
        )
    except Exception as e:
        # Most common cause: the client does not declare the `elicitation`
        # capability (e.g. a headless agent). This is not an operation error
        # but a missing channel to ask the user, so hint both the per-call
        # and the session-level way out.
        raise ICSError(
            "confirm_required",
            f"{action} → {target}: the MCP client does not support confirmations "
            "(elicitation) and the session mode is 'interactive'.",
            hint=(
                "Repeat the call with confirm=true (one-off consent) or "
                "switch the session: ics_session_set_mode('yolo') / "
                "ics_session_set_mode('dry_run')."
            ),
        ) from e
    if getattr(result, "action", None) != "accept":
        raise ICSError(
            "confirm_declined",
            f"{action} → {target}: declined by the user.",
            data={"action": getattr(result, "action", None)},
        )
    data = getattr(result, "data", None)
    chosen = bool(
        data.get("confirm") if isinstance(data, dict) else getattr(data, "confirm", False)
    )
    if not chosen:
        raise ICSError(
            "confirm_declined",
            f"{action} → {target}: not confirmed by the user.",
        )
    return None
