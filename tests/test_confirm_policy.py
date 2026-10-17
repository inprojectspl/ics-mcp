"""Operations that replace content or publish it need a confirmation."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp.config import get_settings
from ics_mcp.tools import session as session_tool
from ics_mcp.tools import share, write_versions
from tests.conftest import call_tool


@pytest.mark.asyncio
@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_new_version_requires_confirmation_in_interactive_mode(
    real_client, respx_mock, make_mcp
):
    mcp = make_mcp(write_versions)
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_new_version",
            {"slug_or_id": "abc", "files": [{"path": "a.md", "content": "# a"}]},
        )
    assert "confirm_required" in str(exc.value)
    assert respx_mock.calls.call_count == 0


@pytest.mark.asyncio
@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_public_link_requires_confirmation_in_interactive_mode(
    real_client, respx_mock, make_mcp
):
    mcp = make_mcp(share)
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_share_create_link", {"slug_or_id": "abc", "mode": "public"})
    assert "confirm_required" in str(exc.value)
    assert respx_mock.calls.call_count == 0


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_org_link_does_not_ask(real_client, respx_mock, make_mcp):
    from tests.conftest import ASSET_ID, ICS, mock_resolve

    mock_resolve(respx_mock)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/shares").mock(
        return_value=httpx.Response(201, json={"id": "s1", "token": "t", "mode": "org_sso"})
    )
    mcp = make_mcp(share)
    await call_tool(mcp, "ics_share_create_link", {"slug_or_id": "abc", "mode": "org_sso"})
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_model_cannot_enable_yolo_without_operator_opt_in(real_client, make_mcp, monkeypatch):
    monkeypatch.setattr(get_settings(), "mcp_allow_yolo", False)
    mcp = make_mcp(session_tool)
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    assert "yolo_disabled" in str(exc.value)
    status = await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    assert status["mode"] == "dry_run"
