"""The registered tool catalog matches the count the CI Inspector step asserts.

The CI workflow checks `tools/list` against a fixed number; reading it from
there keeps one source of truth, so a new tool that forgets the CI bump
fails locally instead of only in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
import respx

from ics_mcp.server import build_mcp
from tests.conftest import ICS, call_tool, list_tools

CI_FILE = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def _ci_tool_count() -> int:
    match = re.search(
        r"assert_count\.py\s+inspector-tools\.json\s+tools\s+(\d+)",
        CI_FILE.read_text(encoding="utf-8"),
    )
    assert match, "MCP Inspector tool count not found in the CI workflow"
    return int(match.group(1))


@pytest.mark.asyncio
async def test_tool_count_matches_ci(settings):
    tools = await list_tools(build_mcp(settings))
    assert len(tools) == _ci_tool_count()


@pytest.mark.asyncio
async def test_metadata_tools_registered(settings):
    names = {t.name for t in await list_tools(build_mcp(settings))}
    assert {"ics_asset_set_meta", "ics_doc_types"} <= names


@pytest.mark.asyncio
async def test_relation_tools_registered(settings):
    names = {t.name for t in await list_tools(build_mcp(settings))}
    assert {
        "ics_asset_relations",
        "ics_relation_add",
        "ics_relation_update",
        "ics_relation_remove",
        "ics_graph_neighbourhood",
    } <= names


def _walk(schema):
    yield schema
    if isinstance(schema, dict):
        for value in schema.values():
            if isinstance(value, dict):
                yield from _walk(value)
            elif isinstance(value, list):
                for item in value:
                    yield from _walk(item)


@pytest.mark.asyncio
async def test_catalog_is_compact(settings):
    """Optional parameters are plain types, generic dict output schemas and
    docstrings in output schemas are gone, shared argument texts are short."""
    tools = await list_tools(build_mcp(settings))
    for tool in tools:
        for node in _walk(tool.parameters):
            if isinstance(node, dict) and isinstance(node.get("anyOf"), list):
                assert {"type": "null"} not in node["anyOf"], tool.name
        assert tool.output_schema != {"type": "object", "additionalProperties": True}, tool.name
        if tool.output_schema:
            assert not any(
                isinstance(n, dict) and isinstance(n.get("description"), str)
                for n in _walk(tool.output_schema)
            ), tool.name
    by_name = {t.name: t for t in tools}
    assert len(by_name["ics_asset_read"].description or "") < 1300
    confirm = by_name["ics_relation_remove"].parameters["properties"]["confirm"]
    assert len(confirm["description"]) < 100


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_explicit_null_still_accepted(real_client, respx_mock, settings):
    """The published schema drops `null`, the Python signature still takes it."""
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/file-mcp").mock(
        return_value=httpx.Response(200, json={"slug": "abc", "path": "a.md", "content": "x"})
    )
    payload = await call_tool(
        build_mcp(settings), "ics_asset_read", {"slug_or_id": "abc", "path": None}
    )
    assert payload["content"] == "x"
