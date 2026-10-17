"""OCR of scanned PDFs (ICS ADR-0021): `ics_asset_ocr` status and request,
the ICS error codes it passes on, and the `ocr_notice` of `ics_asset_read`.
Response mocks follow the ICS `/ocr` and `file-mcp` contract."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp.tools import ocr, read
from ics_mcp.tools.ocr import ocr_notice
from tests.conftest import ASSET_ID, ICS, asset_meta, call_tool


def state(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "not_requested",
        "pages_without_text": 3,
        "available": True,
        "provider": None,
        "requested_at": None,
        "started_at": None,
        "finished_at": None,
        "pages_total": None,
        "pages_done": None,
        "pages_recognized": None,
        "error_code": None,
    }
    base.update(over)
    return base


def test_notice_follows_the_state():
    assert ocr_notice(None) is None
    assert ocr_notice(state(status="done")) is None
    assert ocr_notice(state(pages_without_text=0)) is None
    assert "never requested" in (ocr_notice(state()) or "")
    saved = ocr_notice(state(pages_without_text=0, pages_with_hidden_text=247)) or ""
    assert "247 page(s) are scans" in saved and "request=True" in saved
    assert "turned off" in (ocr_notice(state(available=False)) or "")
    running = ocr_notice(state(status="running", pages_total=3, pages_done=1)) or ""
    assert "page 1 of 3" in running and "Do not wait in a loop" in running
    failed = ocr_notice(state(status="failed", error_code="ocr_timeout")) or ""
    assert "ocr_timeout" in failed and "request=True" in failed


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_status_reads_the_ocr_endpoint(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/rep/ocr").mock(
        return_value=httpx.Response(
            200, json={"slug": "rep", "version": 2, "ocr": state(status="queued")}
        )
    )
    out = await call_tool(make_mcp(ocr), "ics_asset_ocr", {"slug_or_id": "rep"})
    assert out["ocr"]["status"] == "queued"
    assert out["version"] == 2
    assert "queued" in out["notice"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_request_posts_to_the_asset(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/rep/meta").mock(
        return_value=httpx.Response(200, json=asset_meta(slug="rep", kind="pdf_doc"))
    )
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/ocr").mock(
        return_value=httpx.Response(
            202, json={"slug": "rep", "version": 1, "ocr": state(status="queued")}
        )
    )
    out = await call_tool(make_mcp(ocr), "ics_asset_ocr", {"slug_or_id": "rep", "request": True})
    assert route.call_count == 1
    assert out["ocr"]["status"] == "queued"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [(409, "ocr_in_progress"), (409, "ocr_not_needed"), (400, "ocr_not_supported")],
)
@respx.mock(assert_all_called=False)
async def test_request_refusals_keep_the_ics_code(real_client, respx_mock, make_mcp, status, code):
    respx_mock.get(f"{ICS}/api/assets/by-slug/rep/meta").mock(
        return_value=httpx.Response(200, json=asset_meta(slug="rep", kind="pdf_doc"))
    )
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/ocr").mock(
        return_value=httpx.Response(status, json={"detail": "refused", "code": code})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(make_mcp(ocr), "ics_asset_ocr", {"slug_or_id": "rep", "request": True})
    assert json.loads(str(exc.value))["code"] == code


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_read_of_a_scan_in_progress_carries_the_notice(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/rep/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "rep",
                "path": "scan.pdf",
                "content": "# scan\n\n## Page 1\n\n_No text layer on this page (scanned image?)._\n",
                "total_lines": 5,
                "returned_range": [1, 5],
                "format": "markdown",
                "page_count": 1,
                "text_page_count": 0,
                "ocr_page_count": 0,
                "ocr": state(status="running", pages_without_text=1, pages_total=1, pages_done=0),
                "version": 1,
                "current_version": 1,
            },
        )
    )
    out = await call_tool(make_mcp(read), "ics_asset_read", {"slug_or_id": "rep"})
    assert out["ocr"]["status"] == "running"
    assert out["text_page_count"] == 0
    assert "no text yet" in out["ocr_notice"]
