"""pdf_doc support: kind in the read models, PDF search/read/outline shapes,
and the create/replace PDF tools (local file checks, multipart shape, PDF
error codes). Response mocks follow the ICS PDF contract."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp import resources as resources_mod
from ics_mcp.config import get_settings
from ics_mcp.tools import discovery, read, write_documents
from ics_mcp.tools import session as session_tool
from tests.conftest import ASSET_ID, ICS, asset_meta, call_tool, read_resource

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def create_pdf_response(*, title: str | None = "report", **overrides: object) -> dict[str, object]:
    """Shape of the `POST /api/assets/pdf` 201 response from the ICS contract."""
    base: dict[str, object] = {
        "id": ASSET_ID,
        "slug": "rep",
        "title": title,
        "share_url": f"{ICS}/s/tok",
        "page_count": 3,
        "security_status": "clean",
    }
    base.update(overrides)
    return base


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    p = tmp_path / "report.pdf"
    p.write_bytes(PDF_BYTES)
    return p


def _error_payload(exc: pytest.ExceptionInfo[ToolError]) -> dict[str, object]:
    return json.loads(str(exc.value))


# ----------------- read side -----------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_list_and_meta_accept_pdf_doc(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    item = asset_meta(slug="rep", kind="pdf_doc")
    respx_mock.get(f"{ICS}/api/assets/index").mock(
        return_value=httpx.Response(200, json={"items": [item], "next_cursor": None})
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/rep/meta").mock(
        return_value=httpx.Response(200, json=item)
    )
    listing = await call_tool(mcp, "ics_assets_list", {"kind": ["pdf_doc"]})
    assert listing["items"][0]["kind"] == "pdf_doc"
    meta = await call_tool(mcp, "ics_asset_meta", {"slug_or_id": "rep"})
    assert meta["kind"] == "pdf_doc"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_search_keeps_snippet_page(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    hit = {
        "slug": "rep",
        "title": "report",
        "kind": "pdf_doc",
        "snippets": [{"text": "the <em>budget</em> table", "page": 7}],
    }
    respx_mock.get(f"{ICS}/api/assets/search-mcp").mock(
        return_value=httpx.Response(200, json={"items": [hit], "total": 1})
    )
    payload = await call_tool(mcp, "ics_assets_search", {"q": "budget", "kind": ["pdf_doc"]})
    assert payload["items"][0]["snippets"][0]["page"] == 7


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_outline_passes_pdf_shape_through(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    outline = {
        "kind": "pdf_doc",
        "title": "report",
        "page_count": 2,
        "text_page_count": 1,
        "bookmarks": [{"level": 1, "title": "Intro", "page": 1}],
        "headings": [{"level": 2, "text": "Page 1", "line": 3}],
        "line_count": 9,
        "truncated": False,
    }
    respx_mock.get(f"{ICS}/api/assets/by-slug/rep/outline").mock(
        return_value=httpx.Response(200, json=outline)
    )
    payload = await call_tool(mcp, "ics_asset_outline", {"slug_or_id": "rep"})
    assert payload["bookmarks"][0]["page"] == 1
    assert payload["headings"][0]["line"] == 3


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_read_returns_pdf_markdown_with_page_count(real_client, respx_mock, make_mcp):
    mcp = make_mcp(read)
    content = (
        "# report\n\n## Page 1\n\nHello\n\n## Page 2\n\n"
        "_No text layer on this page (scanned image?)._\n"
    )
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/rep/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "rep",
                "path": "report.pdf",
                "content": content,
                "total_lines": 9,
                "returned_range": [1, 9],
                "version": 1,
                "current_version": 1,
                "format": "markdown",
                "page_count": 2,
            },
        )
    )
    payload = await call_tool(mcp, "ics_asset_read", {"slug_or_id": "rep", "lines": "1-9"})
    assert route.calls[0].request.url.params["lines"] == "1-9"
    assert payload["format"] == "markdown"
    assert payload["page_count"] == 2
    assert "## Page 2" in payload["content"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_resource_inlines_pdf_text(real_client, respx_mock, make_mcp):
    mcp = make_mcp(resources_mod)
    respx_mock.get(f"{ICS}/api/assets/by-slug/rep/meta").mock(
        return_value=httpx.Response(200, json={"id": "x", "slug": "rep", "kind": "pdf_doc"})
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/rep/file-mcp").mock(
        return_value=httpx.Response(200, json={"content": "# report\n\n## Page 1\n"})
    )
    result = await read_resource(mcp, "ics://asset/rep")
    data = json.loads(result.contents[0].text)
    assert data["content"].startswith("# report")


# ----------------- ics_asset_create_pdf -----------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_pdf_uploads_multipart_with_query_params(
    real_client, respx_mock, make_mcp, pdf_file
):
    mcp = make_mcp(write_documents)
    project_id = "00000000-0000-0000-0000-000000000003"
    route = respx_mock.post(f"{ICS}/api/assets/pdf").mock(
        return_value=httpx.Response(201, json=create_pdf_response())
    )
    rename = respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "title": "x"})
    )
    payload = await call_tool(
        mcp,
        "ics_asset_create_document",
        {
            "payload": {
                "file_path": str(pdf_file),
                "share_mode": "public",
                "project_id": project_id,
            },
            "confirm": True,
        },
    )
    request = route.calls[0].request
    assert request.url.params["share_mode"] == "public"
    assert request.url.params["project_id"] == project_id
    assert request.headers["content-type"].startswith("multipart/form-data")
    body = request.content
    assert b'name="file"; filename="report.pdf"' in body
    assert b"Content-Type: application/pdf" in body
    assert PDF_BYTES in body
    # The title derived from the file name is kept: no rename call.
    assert rename.call_count == 0
    assert payload["slug"] == "rep"
    assert payload["page_count"] == 3
    assert payload["kind"] == "pdf_doc"
    assert payload["security_status"] == "clean"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_pdf_applies_title_via_rename(real_client, respx_mock, make_mcp, pdf_file):
    mcp = make_mcp(write_documents)
    respx_mock.post(f"{ICS}/api/assets/pdf").mock(
        return_value=httpx.Response(201, json=create_pdf_response())
    )
    rename = respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "title": "Q3 report"})
    )
    payload = await call_tool(
        mcp,
        "ics_asset_create_document",
        {"payload": {"file_path": str(pdf_file), "title": "Q3 report"}},
    )
    assert json.loads(rename.calls[0].request.content) == {"title": "Q3 report"}
    assert payload["title"] == "Q3 report"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_pdf_rejects_file_without_signature(
    real_client, respx_mock, make_mcp, tmp_path
):
    mcp = make_mcp(write_documents)
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"<html>not a pdf</html>")
    route = respx_mock.post(f"{ICS}/api/assets/pdf")
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_create_document", {"payload": {"file_path": str(fake)}})
    assert _error_payload(exc)["code"] == "invalid_pdf"
    assert route.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("notes.txt", "document_file_required"),
        # The extension picks the kind: PDF bytes named .docx are no Word file.
        ("notes.docx", "invalid_office_document"),
        ("missing.pdf", "invalid_argument"),
    ],
)
async def test_create_pdf_rejects_bad_path(real_client, make_mcp, tmp_path, name, code):
    mcp = make_mcp(write_documents)
    target = tmp_path / name
    if not name.startswith("missing"):
        target.write_bytes(PDF_BYTES)
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_create_document", {"payload": {"file_path": str(target)}})
    assert _error_payload(exc)["code"] == code


@pytest.mark.asyncio
async def test_create_pdf_refuses_file_path_over_http(real_client, make_mcp, pdf_file, monkeypatch):
    monkeypatch.setattr(get_settings(), "mcp_transport", "http")
    mcp = make_mcp(write_documents)
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_create_document", {"payload": {"file_path": str(pdf_file)}})
    assert _error_payload(exc)["code"] == "invalid_argument"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_pdf_promotes_backend_pdf_code(real_client, respx_mock, make_mcp, pdf_file):
    mcp = make_mcp(write_documents)
    respx_mock.post(f"{ICS}/api/assets/pdf").mock(
        return_value=httpx.Response(
            400, json={"detail": "The PDF is password protected", "code": "pdf_encrypted"}
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_create_document", {"payload": {"file_path": str(pdf_file)}})
    err = _error_payload(exc)
    assert err["code"] == "pdf_encrypted"
    assert err["status"] == 400
    assert "hint" in err


# ----------------- ics_asset_replace_pdf -----------------


def _mock_pdf_meta(respx_mock, kind: str = "pdf_doc"):
    return respx_mock.get(f"{ICS}/api/assets/by-slug/rep/meta").mock(
        return_value=httpx.Response(200, json=asset_meta(slug="rep", kind=kind))
    )


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_replace_pdf_posts_one_file_in_files_field(
    real_client, respx_mock, make_mcp, pdf_file
):
    mcp = make_mcp(write_documents, session_tool)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    _mock_pdf_meta(respx_mock)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions").mock(
        return_value=httpx.Response(201, json={"id": ASSET_ID, "version": 2})
    )
    payload = await call_tool(
        mcp, "ics_asset_replace_document", {"slug_or_id": "rep", "file_path": str(pdf_file)}
    )
    body = route.calls[0].request.content
    assert body.count(b'name="files"') == 1
    assert b'filename="report.pdf"' in body
    assert b"Content-Type: application/pdf" in body
    assert payload["version"] == 2


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_replace_pdf_dry_run_sends_nothing(real_client, respx_mock, make_mcp, pdf_file):
    mcp = make_mcp(write_documents, session_tool)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions")
    payload = await call_tool(
        mcp, "ics_asset_replace_document", {"slug_or_id": "rep", "file_path": str(pdf_file)}
    )
    assert route.call_count == 0
    assert payload["action"] == "replace_document"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_replace_pdf_refuses_other_kinds(real_client, respx_mock, make_mcp, pdf_file):
    mcp = make_mcp(write_documents)
    _mock_pdf_meta(respx_mock, kind="md_single")
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions")
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_replace_document",
            {"slug_or_id": "rep", "file_path": str(pdf_file), "confirm": True},
        )
    err = _error_payload(exc)
    assert err["code"] == "wrong_kind"
    assert "ics_asset_new_version" in str(err["hint"])
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_replace_pdf_promotes_too_large(real_client, respx_mock, make_mcp, pdf_file):
    mcp = make_mcp(write_documents)
    _mock_pdf_meta(respx_mock)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions").mock(
        return_value=httpx.Response(413, json={"detail": "PDF too large", "code": "pdf_too_large"})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_replace_document",
            {"slug_or_id": "rep", "file_path": str(pdf_file), "confirm": True},
        )
    assert _error_payload(exc)["code"] == "pdf_too_large"
