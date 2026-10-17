"""Spec-compliant tool annotation presets (MCP 2025-11-25 §server/tools).

Imported as `A.RO_IDEMP` etc. in tool modules so any future spec field
gets added in exactly one place.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations


def _anno(*, ro: bool, dest: bool, idemp: bool, open_world: bool = False) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=ro,
        destructiveHint=dest,
        idempotentHint=idemp,
        openWorldHint=open_world,
    )


RO_IDEMP: ToolAnnotations = _anno(ro=True, dest=False, idemp=True)
MUTATING: ToolAnnotations = _anno(ro=False, dest=False, idemp=False)
MUTATING_IDEMP: ToolAnnotations = _anno(ro=False, dest=False, idemp=True)
DESTRUCTIVE: ToolAnnotations = _anno(ro=False, dest=True, idemp=False)
DESTRUCTIVE_IDEMP: ToolAnnotations = _anno(ro=False, dest=True, idemp=True)
MUTATING_OPEN_WORLD: ToolAnnotations = _anno(ro=False, dest=False, idemp=False, open_world=True)
