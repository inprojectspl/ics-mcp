"""Versioned resource templates read archived versions through `?version=`."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp.exceptions import ResourceError

from ics_mcp import resources as resources_mod
from tests.conftest import ICS, read_resource


def _text(result) -> str:
    contents = getattr(result, "contents", result)
    return "".join(getattr(c, "text", "") or "" for c in contents)


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_version_resource_md_reads_version(real_client, respx_mock, make_mcp):
    mcp = make_mcp(resources_mod)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").mock(
        return_value=httpx.Response(200, json={"id": "x", "slug": "abc", "kind": "md_single"})
    )
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/file-mcp").mock(
        return_value=httpx.Response(200, json={"content": "Old text"})
    )
    result = await read_resource(mcp, "ics://asset/abc@v2")
    assert route.called
    assert route.calls.last.request.url.params["version"] == "2"
    body = _text(result)
    assert "Old text" in body
    assert '"read_version": 2' in body or '"read_version":2' in body


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_version_resource_collection_lists_version_files(
    real_client, respx_mock, make_mcp
):
    mcp = make_mcp(resources_mod)
    respx_mock.get(f"{ICS}/api/assets/by-slug/coll/meta").mock(
        return_value=httpx.Response(200, json={"id": "x", "slug": "coll", "kind": "md_collection"})
    )
    outline = respx_mock.get(f"{ICS}/api/assets/by-slug/coll/outline")
    files = respx_mock.get(f"{ICS}/api/assets/by-slug/coll/files-mcp").mock(
        return_value=httpx.Response(200, json={"files": [{"path": "old.md"}]})
    )
    result = await read_resource(mcp, "ics://asset/coll@v3")
    assert files.calls.last.request.url.params["version"] == "3"
    assert not outline.called
    assert "old.md" in _text(result)


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_version_file_resource_reads_version(real_client, respx_mock, make_mcp):
    mcp = make_mcp(resources_mod)
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/coll/file-mcp").mock(
        return_value=httpx.Response(200, json={"content": "# Chapter v2"})
    )
    result = await read_resource(mcp, "ics://asset/coll@v2/file/chapter.md")
    params = route.calls.last.request.url.params
    assert params["version"] == "2"
    assert params["path"] == "chapter.md"
    assert "# Chapter v2" in _text(result)


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_unversioned_file_resource_sends_no_version(real_client, respx_mock, make_mcp):
    mcp = make_mcp(resources_mod)
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/coll/file-mcp").mock(
        return_value=httpx.Response(200, json={"content": "current"})
    )
    await read_resource(mcp, "ics://asset/coll/file/chapter.md")
    assert "version" not in route.calls.last.request.url.params


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_invalid_version_is_rejected_before_ics(real_client, respx_mock, make_mcp):
    mcp = make_mcp(resources_mod)
    route = respx_mock.get(url__startswith=f"{ICS}/api/assets/by-slug/abc/")
    with pytest.raises(ResourceError):
        await read_resource(mcp, "ics://asset/abc@v0")
    assert not route.called
