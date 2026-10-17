"""Confirmation for create tools asked to publish the new asset with a
`public` link: anyone with the URL can read it, so creating one goes through
the same gate as `ics_share_create_link(mode="public")`."""

from __future__ import annotations

from typing import Any

from fastmcp import Context
from fastmcp.utilities.json_schema import compress_schema
from pydantic import BaseModel

from ics_mcp._helpers import get_mode
from ics_mcp.confirm import confirm_or_skip

# The dict `confirm_or_skip` returns in dry_run mode.
_PREVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "target": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["action", "target", "note"],
}


def output_or_preview(model: type[BaseModel]) -> dict[str, Any]:
    """Output schema accepting `model` or the dry-run preview. Clients
    validate `structuredContent` against it, and a return annotation union
    would make FastMCP wrap every result in `{"result": ...}`."""
    schema = compress_schema(model.model_json_schema(mode="serialization"), prune_titles=True)
    defs = schema.pop("$defs", None)
    out: dict[str, Any] = {"type": "object", "anyOf": [schema, _PREVIEW_SCHEMA]}
    if defs:
        out["$defs"] = defs
    return out


async def confirm_public_create(
    ctx: Context, share_mode: str | None, *, target: str, confirm: bool | None
) -> dict[str, Any] | None:
    """`None` when the create may run; the dry-run preview otherwise.
    Raises `ICSError` on refusal, like `ics_share_create_link`."""
    if share_mode != "public":
        return None
    return await confirm_or_skip(
        ctx,
        action="create_public_link",
        target=target,
        confirm=confirm,
        mode=get_mode(ctx),
    )
