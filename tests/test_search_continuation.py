"""Search limits must preserve hits, order and reachable continuation."""

from __future__ import annotations

import httpx
import pytest
import respx

from ics_mcp._payload import payload_chars
from ics_mcp.config import get_settings
from ics_mcp.tools import discovery
from tests.conftest import ICS, call_tool


@pytest.mark.parametrize("detail", ["compact", "full"])
@respx.mock(assert_all_called=False)
async def test_large_search_pages_keep_every_hit_reachable(
    real_client, respx_mock, make_mcp, detail
):
    mcp = make_mcp(discovery)
    items = [
        {
            "slug": f"doc-{i}",
            "title": f"Hit {i}",
            "kind": "md_single",
            "score": 1,
            "snippets": [{"text": "word " * 400}],
        }
        for i in range(12)
    ]

    def respond(request):
        params = request.url.params
        offset, limit = int(params["offset"]), int(params["limit"])
        assert params["q"] == '"Crème brûlée"'
        assert params["match"] == "any"
        return httpx.Response(
            200,
            json={
                "items": items[offset : offset + limit],
                "total": len(items),
                "offset": offset,
                "limit": limit,
                "has_more": offset + limit < len(items),
            },
        )

    respx_mock.get(f"{ICS}/api/assets/search-mcp").mock(side_effect=respond)
    offset = 0
    found = []
    while True:
        page = await call_tool(
            mcp,
            "ics_assets_search",
            {
                "q": '"Crème brûlée"',
                "match": "any",
                "limit": 12,
                "offset": offset,
                "detail": detail,
            },
        )
        assert page["items"]
        assert page["total"] == 12
        assert payload_chars(page) <= get_settings().mcp_response_max_chars
        found.extend(hit["slug"] for hit in page["items"])
        if "next_offset" not in page:
            break
        assert page["next_offset"] == offset + len(page["items"])
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert found == [item["slug"] for item in items]


@respx.mock(assert_all_called=False)
async def test_single_oversized_hit_keeps_identity_and_next_offset(
    real_client, respx_mock, make_mcp
):
    mcp = make_mcp(discovery)
    respx_mock.get(f"{ICS}/api/assets/search-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"slug": "huge", "title": "Title", "snippets": [{"text": "x" * 50000}]}],
                "total": 2,
                "limit": 1,
                "offset": 600,
                "has_more": True,
            },
        )
    )
    page = await call_tool(mcp, "ics_assets_search", {"q": "huge", "offset": 600})
    assert page["items"][0]["slug"] == "huge"
    assert page["next_offset"] == 601
    assert page["truncated"] is True
    assert payload_chars(page) <= get_settings().mcp_response_max_chars
