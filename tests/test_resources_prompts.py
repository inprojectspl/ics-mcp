"""Resources + Prompts: registration smoke + read paths against fake ICS."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from ics_mcp import prompts as prompts_mod
from ics_mcp import resources as resources_mod
from tests.conftest import ICS, get_prompt, read_resource


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resource_index_reads_assets(real_client, respx_mock, make_mcp):
    mcp = make_mcp(resources_mod)
    respx_mock.get(f"{ICS}/api/assets/index").mock(
        return_value=httpx.Response(200, json={"items": [], "next_cursor": None})
    )
    assert await read_resource(mcp, "ics://index") is not None


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resource_asset_md_inlines_content(real_client, respx_mock, make_mcp):
    mcp = make_mcp(resources_mod)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").mock(
        return_value=httpx.Response(200, json={"id": "x", "slug": "abc", "kind": "md_single"})
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/file-mcp").mock(
        return_value=httpx.Response(200, json={"content": "Hello"})
    )
    assert await read_resource(mcp, "ics://asset/abc") is not None


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resource_asset_collection_returns_outline(real_client, respx_mock, make_mcp):
    mcp = make_mcp(resources_mod)
    respx_mock.get(f"{ICS}/api/assets/by-slug/coll/meta").mock(
        return_value=httpx.Response(200, json={"id": "x", "slug": "coll", "kind": "md_collection"})
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/coll/outline").mock(
        return_value=httpx.Response(200, json={"kind": "md_collection", "files": []})
    )
    assert await read_resource(mcp, "ics://asset/coll") is not None


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resource_outline_endpoint(real_client, respx_mock, make_mcp):
    mcp = make_mcp(resources_mod)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/outline").mock(
        return_value=httpx.Response(200, json={"kind": "md_single"})
    )
    assert await read_resource(mcp, "ics://asset/abc/outline") is not None


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resource_project(real_client, respx_mock, make_mcp):
    mcp = make_mcp(resources_mod)
    respx_mock.get(f"{ICS}/api/projects/proj").mock(
        return_value=httpx.Response(200, json={"slug": "proj", "name": "P"})
    )
    assert await read_resource(mcp, "ics://project/proj") is not None


@pytest.mark.parametrize(
    "slug, asset_count, truncated, expect_hint",
    [("big", 543, True, True), ("small", 3, False, False)],
)
@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resource_project_truncation_hint(
    real_client,
    respx_mock,
    make_mcp,
    slug,
    asset_count,
    truncated,
    expect_hint,
):
    """ICS caps the asset list at 200 and flags `assets_truncated`.
    MCP appends a `hint` saying what to do next, but only when something was
    actually cut off, so complete projects stay uncluttered."""
    mcp = make_mcp(resources_mod)
    respx_mock.get(f"{ICS}/api/projects/{slug}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "p-uuid",
                "slug": slug,
                "asset_count": asset_count,
                "assets": [],
                "assets_truncated": truncated,
            },
        )
    )
    result = await read_resource(mcp, f"ics://project/{slug}")
    data = json.loads(result.contents[0].text)
    if expect_hint:
        assert "hint" in data
        assert f"200/{asset_count}" in data["hint"]
        assert "p-uuid" in data["hint"]
    else:
        assert "hint" not in data


@pytest.mark.asyncio
async def test_prompt_share_with_team_renders(make_mcp):
    mcp = make_mcp(prompts_mod)
    result = await get_prompt(mcp, "share_with_team", {"asset_slug": "abc"})
    assert "abc" in result.messages[0].content.text


@pytest.mark.asyncio
async def test_prompt_share_with_team_with_password_hint(make_mcp):
    mcp = make_mcp(prompts_mod)
    result = await get_prompt(
        mcp,
        "share_with_team",
        {"asset_slug": "abc", "mode": "password", "password_hint": "Slack DM"},
    )
    text = result.messages[0].content.text
    assert "Slack DM" in text
    assert "password='...'" in text


@pytest.mark.asyncio
async def test_prompt_summarize_collection_renders(make_mcp):
    mcp = make_mcp(prompts_mod)
    result = await get_prompt(mcp, "summarize_collection", {"slug": "abc"})
    assert "abc" in result.messages[0].content.text


@pytest.mark.asyncio
async def test_prompt_migrate_to_collection_renders(make_mcp):
    mcp = make_mcp(prompts_mod)
    result = await get_prompt(mcp, "migrate_to_collection", {"source_slug": "x", "new_title": "Y"})
    text = result.messages[0].content.text
    assert "x" in text
    assert "Y" in text
