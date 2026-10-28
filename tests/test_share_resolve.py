"""Tests for `ics_share_resolve`: token/URL parsing and the pass-through to
`POST /api/share/{token}/resolve`."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp._helpers import extract_share_token
from ics_mcp.tools import share
from tests.conftest import ICS, call_tool

TOKEN = "test-share-token-not-real"


def _resolve_response(**overrides) -> dict:
    body = {
        "share": {
            "mode": "public",
            "expires_at": None,
            "view_count": 1,
            "max_views": None,
        },
        "asset": {
            "id": "12345678-1234-5678-1234-567812345678",
            "slug": "abc",
            "title": "Doc",
            "kind": "md_single",
            "version": 1,
            "entry_path": "doc.md",
            "size_bytes": 42,
            "security_status": "clean",
            "created_at": "2026-06-01T10:00:00Z",
            "updated_at": "2026-06-01T10:00:00Z",
        },
        "path": "doc.md",
        "content": "# Hello",
        "tree": None,
        "files": None,
    }
    body.update(overrides)
    return body


# ----------------- extract_share_token -----------------


@pytest.mark.parametrize(
    "ref",
    [
        TOKEN,
        f"  {TOKEN}  ",
        f"https://ics.example.com/s/{TOKEN}",
        f"https://ics.example.com/s/{TOKEN}?m=magic-payload",
        f"https://ics.example.com/s/{TOKEN}#frag",
        f"/s/{TOKEN}",
    ],
)
def test_extract_share_token_accepts_token_and_urls(ref):
    assert extract_share_token(ref) == TOKEN


@pytest.mark.parametrize(
    "ref",
    [
        "https://ics.example.com/assets/abc",  # no /s/ segment
        "https://ics.example.com/s/",  # empty token
        "too short",  # a space means not a token
        "x",  # below the minimum length
        "tok!en-with-forbidden-characters",
    ],
)
def test_extract_share_token_rejects_garbage(ref):
    with pytest.raises(ToolError) as exc:
        extract_share_token(ref)
    assert "bad_share_link" in str(exc.value)


# ----------------- tool e2e (respx) -----------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resolve_public_share_from_url(real_client, respx_mock, make_mcp):
    mcp = make_mcp(share)
    route = respx_mock.post(f"{ICS}/api/share/{TOKEN}/resolve").mock(
        return_value=httpx.Response(200, json=_resolve_response())
    )
    payload = await call_tool(
        mcp,
        "ics_share_resolve",
        {"share_link": f"https://ics.example.com/s/{TOKEN}"},
    )
    assert payload["content"] == "# Hello"
    assert payload["asset"]["slug"] == "abc"
    assert payload["share"]["mode"] == "public"
    # without a password or path the body is empty; we do not send nulls
    assert json.loads(route.calls.last.request.content) == {}


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resolve_forwards_password_path_and_format(real_client, respx_mock, make_mcp):
    mcp = make_mcp(share)
    route = respx_mock.post(f"{ICS}/api/share/{TOKEN}/resolve").mock(
        return_value=httpx.Response(
            200,
            json=_resolve_response(
                path="notes/foo.md",
                content="# Foo",
                tree=["index.md", "notes/foo.md"],
            ),
        )
    )
    payload = await call_tool(
        mcp,
        "ics_share_resolve",
        {"share_link": TOKEN, "password": "s3cret", "path": "notes/foo.md", "format": "markdown"},
    )
    assert payload["content"] == "# Foo"
    assert payload["tree"] == ["index.md", "notes/foo.md"]
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"password": "s3cret", "path": "notes/foo.md", "format": "markdown"}


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resolve_password_required_maps_401(real_client, respx_mock, make_mcp):
    mcp = make_mcp(share)
    respx_mock.post(f"{ICS}/api/share/{TOKEN}/resolve").mock(
        return_value=httpx.Response(
            401,
            json={"detail": "this link is password protected, pass it in the `password` field"},
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_share_resolve", {"share_link": TOKEN})
    msg = str(exc.value)
    assert "unauthorized" in msg
    assert "password" in msg


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resolve_gone_maps_410(real_client, respx_mock, make_mcp):
    mcp = make_mcp(share)
    respx_mock.post(f"{ICS}/api/share/{TOKEN}/resolve").mock(
        return_value=httpx.Response(410, json={"detail": "the link has been revoked"})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_share_resolve", {"share_link": TOKEN})
    assert "gone" in str(exc.value)


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resolve_forwards_lines_and_returns_range_meta(real_client, respx_mock, make_mcp):
    mcp = make_mcp(share)
    route = respx_mock.post(f"{ICS}/api/share/{TOKEN}/resolve").mock(
        return_value=httpx.Response(
            200,
            json=_resolve_response(content="line 10", total_lines=50, returned_range=[10, 10]),
        )
    )
    payload = await call_tool(mcp, "ics_share_resolve", {"share_link": TOKEN, "lines": "10-10"})
    assert payload["total_lines"] == 50
    assert payload["returned_range"] == [10, 10]
    assert json.loads(route.calls.last.request.content) == {"lines": "10-10"}


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resolve_truncation_hint_points_at_share_resolve(real_client, respx_mock, make_mcp):
    """The hint on a truncated response must lead through share resolve
    (lines/path), not through asset tools that need a role on the asset."""
    mcp = make_mcp(share)
    respx_mock.post(f"{ICS}/api/share/{TOKEN}/resolve").mock(
        return_value=httpx.Response(200, json=_resolve_response(content="x" * 100_000))
    )
    payload = await call_tool(mcp, "ics_share_resolve", {"share_link": TOKEN})
    assert payload["truncated"] is True
    assert "ics_share_resolve" in payload["hint"]
    assert "ics_asset_read" not in payload["hint"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resolve_accepts_a_document_without_title(real_client, respx_mock, make_mcp):
    mcp = make_mcp(share)
    body = _resolve_response()
    body["asset"]["title"] = None
    respx_mock.post(f"{ICS}/api/share/{TOKEN}/resolve").mock(
        return_value=httpx.Response(200, json=body)
    )

    payload = await call_tool(mcp, "ics_share_resolve", {"share_link": TOKEN})

    assert payload["asset"]["slug"] == "abc"
    assert payload["asset"]["title"] is None
    assert payload["content"] == "# Hello"
