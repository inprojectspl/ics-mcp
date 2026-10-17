"""Every failure inside a tool reaches the model as a structured error."""

from __future__ import annotations

import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp._helpers import map_ics_errors, promote_error
from ics_mcp.errors import ICSError
from ics_mcp.tools import write_md
from tests.conftest import call_tool, mock_resolve


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_binary_content_path_is_invalid_argument(real_client, respx_mock, make_mcp, tmp_path):
    mock_resolve(respx_mock)
    blob = tmp_path / "image.bin"
    blob.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF")
    mcp = make_mcp(write_md)
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_update_content",
            {"slug_or_id": "abc", "content_path": str(blob), "confirm": True},
        )
    assert "invalid_argument" in str(exc.value)


@pytest.mark.asyncio
async def test_unexpected_exception_becomes_internal_error(capsys):
    from ics_mcp import logging as ics_logging

    ics_logging.configure("INFO")

    @map_ics_errors
    async def broken() -> None:
        raise KeyError("missing")

    with pytest.raises(ToolError) as exc:
        await broken()
    assert "internal_error" in str(exc.value)
    assert "KeyError" in str(exc.value)
    captured = capsys.readouterr()
    assert "unhandled error in tool" in captured.err
    assert "unhandled error in tool" not in captured.out


def test_promote_error_adds_the_table_hint_to_an_ics_error():
    e = ICSError("metadata_invalid", "bad", hint="old", status=400, field="summary")
    out = promote_error(e, {"metadata_invalid": "Fix the summary."})
    assert (out.code, out.field, out.hint, out.status) == (
        "metadata_invalid",
        "summary",
        "Fix the summary.",
        400,
    )
    # A code outside the table keeps its hint.
    assert promote_error(e, {}) is e
    # Errors raised by the tool itself carry no HTTP status and pass unchanged.
    local = ICSError("invalid_argument", "nothing to change")
    assert promote_error(local, {"invalid_argument": "x"}) is local


@pytest.mark.asyncio
async def test_map_ics_errors_with_hints_adds_the_hint():
    @map_ics_errors(hints={"relation_self": "Pick another target."})
    async def tool() -> None:
        raise ICSError("relation_self", "self", status=400)

    with pytest.raises(ToolError) as exc:
        await tool()
    assert '"code": "relation_self"' in str(exc.value)
    assert "Pick another target." in str(exc.value)


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_top_level_code_is_the_ics_code(real_client, respx_mock, make_mcp):
    """The agent sees the ICS `code` and `field` on top, not the HTTP guess,
    and `data` does not repeat them."""
    import json

    import httpx

    from ics_mcp.tools import discovery
    from tests.conftest import ICS

    respx_mock.get(f"{ICS}/api/assets/by-slug/gone/meta").mock(
        return_value=httpx.Response(
            404, json={"detail": "asset not found", "code": "asset_not_found", "field": "slug"}
        )
    )
    mcp = make_mcp(discovery)
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_meta", {"slug_or_id": "gone"})
    err = json.loads(str(exc.value))
    assert err["code"] == "asset_not_found"
    assert err["field"] == "slug"
    assert err["status"] == 404
    assert "data" not in err
