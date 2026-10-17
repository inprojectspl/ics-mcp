"""Compact the published tool catalogue (`tools/list`), which the model gets in
every session: optional parameters are published as their plain type (the
Python signature still accepts `null`), the generic `dict` output schema is
dropped, and output schemas lose their developer-facing `description`s but
keep `null` in their types, since clients validate `structuredContent`."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastmcp.server.transforms import GetToolNext, Transform
from fastmcp.tools import Tool
from fastmcp.utilities.versions import VersionSpec

_GENERIC_OBJECT = {"type": "object", "additionalProperties": True}
_NULL = {"type": "null"}


def _flatten_optional(prop: dict[str, Any]) -> dict[str, Any]:
    """`prop` without its `null` alternative (and the `null` default)."""
    variants = prop.get("anyOf")
    if not isinstance(variants, list) or _NULL not in variants:
        return prop
    rest = [v for v in variants if v != _NULL]
    out = {k: v for k, v in prop.items() if k != "anyOf"}
    if out.get("default", 0) is None:
        del out["default"]
    if len(rest) == 1:
        return {**rest[0], **out}
    return {**out, "anyOf": rest}


def compact_input(schema: dict[str, Any]) -> dict[str, Any]:
    """Input schema with optional parameters as plain types, recursively
    (nested models such as `payload`, list items, `$defs`)."""
    out = dict(schema)
    props = schema.get("properties")
    if isinstance(props, dict):
        required = set(schema.get("required") or [])
        out["properties"] = {
            name: compact_input(prop if name in required else _flatten_optional(prop))
            for name, prop in props.items()
        }
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            out[key] = compact_input(schema[key])
    if isinstance(schema.get("$defs"), dict):
        out["$defs"] = {k: compact_input(v) for k, v in schema["$defs"].items()}
    for key in ("anyOf", "oneOf", "allOf"):
        if isinstance(schema.get(key), list):
            out[key] = [compact_input(v) if isinstance(v, dict) else v for v in schema[key]]
    return out


def compact_output(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """Output schema without the generic dict schema and without docstrings."""
    if schema is None or schema == _GENERIC_OBJECT:
        return None
    return _strip_descriptions(schema)


def _strip_descriptions(schema: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in schema.items() if k != "description"}
    if isinstance(schema.get("properties"), dict):
        out["properties"] = {k: _strip_descriptions(v) for k, v in schema["properties"].items()}
    if isinstance(schema.get("$defs"), dict):
        out["$defs"] = {k: _strip_descriptions(v) for k, v in schema["$defs"].items()}
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            out[key] = _strip_descriptions(schema[key])
    for key in ("anyOf", "oneOf", "allOf"):
        if isinstance(schema.get(key), list):
            out[key] = [_strip_descriptions(v) if isinstance(v, dict) else v for v in schema[key]]
    return out


def compact_tool(tool: Tool) -> Tool:
    return tool.model_copy(
        update={
            "parameters": compact_input(tool.parameters),
            "output_schema": compact_output(tool.output_schema),
        }
    )


class CompactCatalog(Transform):
    """Applies `compact_tool` to listed tools and to the tool a call runs, so
    both see the same schemas. Results are cached per tool object."""

    def __init__(self) -> None:
        self._cache: dict[int, tuple[Tool, Tool]] = {}

    def _compact(self, tool: Tool) -> Tool:
        hit = self._cache.get(id(tool))
        if hit is not None and hit[0] is tool:
            return hit[1]
        compacted = compact_tool(tool)
        self._cache[id(tool)] = (tool, compacted)
        return compacted

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return [self._compact(t) for t in tools]

    async def get_tool(
        self, name: str, call_next: GetToolNext, *, version: VersionSpec | None = None
    ) -> Tool | None:
        tool = await call_next(name, version=version)
        return self._compact(tool) if tool is not None else None
