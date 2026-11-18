"""Archive and trash tools (ICS ADR-0029)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp.tools import discovery, lifecycle
from ics_mcp.tools import session as session_tool
from tests.conftest import ASSET_ID, ICS, asset_meta, call_tool, mock_resolve


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_archive_and_back(real_client, respx_mock, make_mcp):
    mcp = make_mcp(lifecycle)
    mock_resolve(respx_mock)
    into = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/archive").mock(
        return_value=httpx.Response(
            200, json={"id": ASSET_ID, "archived_at": "2026-11-18T10:00:00Z", "noop": False}
        )
    )
    out = respx_mock.delete(f"{ICS}/api/assets/{ASSET_ID}/archive").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "archived_at": None, "noop": False})
    )
    archived = await call_tool(mcp, "ics_asset_archive", {"slug_or_id": "abc"})
    assert archived["archived_at"] and into.call_count == 1
    back = await call_tool(mcp, "ics_asset_archive", {"slug_or_id": "abc", "archived": False})
    assert back["archived_at"] is None and out.call_count == 1


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_list_browses_the_archive_and_marks_its_items(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    route = respx_mock.get(f"{ICS}/api/assets/index").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [asset_meta(archived_at="2026-11-18T10:00:00Z")],
                "next_cursor": None,
            },
        )
    )
    page = await call_tool(mcp, "ics_assets_list", {"archive": "archived"})
    assert route.calls.last.request.url.params["archive"] == "archived"
    assert page["items"][0]["archived"] is True
    await call_tool(mcp, "ics_assets_list", {})
    # The default leaves the parameter out, so an older ICS sees the same call.
    assert "archive" not in route.calls.last.request.url.params


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_search_passes_the_archive_view(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    route = respx_mock.get(f"{ICS}/api/assets/search-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"slug": "abc", "title": "T", "kind": "md_single", "archived": True}],
                "total": 1,
                "has_more": False,
            },
        )
    )
    page = await call_tool(mcp, "ics_assets_search", {"q": "plan", "archive": "all"})
    assert route.calls.last.request.url.params["archive"] == "all"
    assert page["items"][0]["archived"] is True


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_trash_list_narrows_to_a_project(real_client, respx_mock, make_mcp):
    mcp = make_mcp(lifecycle)
    project = "11111111-2222-3333-4444-555555555555"
    route = respx_mock.get(f"{ICS}/api/assets/trash").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0, "next_offset": None})
    )
    await call_tool(mcp, "ics_trash_list", {"project_id": project, "limit": 10})
    params = route.calls.last.request.url.params
    assert params["project_id"] == project and params["limit"] == "10"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_purge_asks_first_and_needs_the_uuid(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, lifecycle)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/purge").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "purged": True})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_purge", {"asset_id": ASSET_ID, "confirm": False})
    assert json.loads(str(exc.value))["code"] == "confirm_required"
    assert route.call_count == 0

    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    preview = await call_tool(mcp, "ics_asset_purge", {"asset_id": ASSET_ID})
    assert preview["action"] == "purge_asset" and route.call_count == 0

    done = await call_tool(mcp, "ics_asset_purge", {"asset_id": ASSET_ID, "confirm": True})
    assert done["purged"] is True and route.call_count == 1

    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_purge", {"asset_id": "abc", "confirm": True})
    assert json.loads(str(exc.value))["code"] == "id_required"
