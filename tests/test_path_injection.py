"""Identifiers cannot steer a request outside its endpoint."""

from __future__ import annotations

import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp.errors import ICSError
from ics_mcp.ics_client import checked_path
from ics_mcp.tools import discovery
from tests.conftest import call_tool


@pytest.mark.parametrize(
    "path",
    [
        "/api/assets/by-slug/../../admin/users/meta",
        "/api/assets/by-slug/./meta",
        "/api/assets/by-slug/x?role=admin/meta",
        "/api/assets/by-slug/x#frag",
        "/api/assets/by-slug/%2e%2e/admin",
        "/api/assets/by-slug/a%2Fb/meta",
        "api/assets",
    ],
)
def test_unsafe_paths_are_rejected(path):
    with pytest.raises(ICSError) as exc:
        checked_path(path)
    assert exc.value.code == "invalid_argument"


def test_plain_paths_pass():
    assert checked_path("/api/assets/by-slug/abc-123/meta") == "/api/assets/by-slug/abc-123/meta"


@pytest.mark.asyncio
@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_asset_meta_with_traversal_slug_sends_no_request(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_meta", {"slug_or_id": "../../admin/users"})
    assert "invalid_argument" in str(exc.value)
    assert respx_mock.calls.call_count == 0
