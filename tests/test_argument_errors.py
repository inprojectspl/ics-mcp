"""A bad tool argument is a structured `invalid_argument` error with the
field and, for enums, the allowed values, not pydantic's text."""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError

from ics_mcp.server import build_mcp


async def _error(settings, tool: str, args: dict) -> dict:
    with pytest.raises(ToolError) as exc:
        await build_mcp(settings)._call_tool_mcp(tool, args)
    return json.loads(str(exc.value))


@pytest.mark.asyncio
async def test_bad_enum_lists_allowed_values(settings):
    err = await _error(
        settings,
        "ics_relation_add",
        {"source": "a", "target": "b", "relation_type": "blocks"},
    )
    assert err["code"] == "invalid_argument"
    assert err["field"] == "relation_type"
    assert "blocks" in err["message"]
    assert "derived_from" in err["data"]["allowed"]
    assert "pydantic" not in json.dumps(err)


@pytest.mark.asyncio
async def test_missing_argument_names_the_field(settings):
    err = await _error(settings, "ics_task_link", {"slug_or_id": "a", "wp": "1"})
    assert err["code"] == "invalid_argument"
    assert err["field"] == "role"
    assert err["message"] == "Missing required argument `role`."


@pytest.mark.asyncio
async def test_several_errors_are_all_reported(settings):
    err = await _error(
        settings,
        "ics_graph_neighbourhood",
        {"slug_or_id": "a", "direction": "up", "depth": 9},
    )
    fields = {err["field"], *(e["field"] for e in err["data"]["errors"])}
    assert fields == {"direction", "depth"}
