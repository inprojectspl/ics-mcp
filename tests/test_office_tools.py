"""office_doc support: kind in the read models, office read/outline shapes,
and the create/replace document tools (local file checks, multipart shape,
office error codes). Response mocks follow the ICS office document contract."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp import resources as resources_mod
from ics_mcp.config import get_settings
from ics_mcp.tools import discovery, read, write_documents, write_office
from ics_mcp.tools import session as session_tool
from tests.conftest import ASSET_ID, ICS, asset_meta, call_tool, read_resource

DOCX_BYTES = b"PK\x03\x04\x14\x00\x06\x00[Content_Types].xml fake docx body"
DOC_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def create_document_response(**overrides: object) -> dict[str, object]:
    """Shape of the `POST /api/assets/document` 201 response from the ICS contract."""
    base: dict[str, object] = {
        "id": ASSET_ID,
        "slug": "memo",
        "title": "memo",
        "kind": "office_doc",
        "share_url": f"{ICS}/s/tok",
        "security_status": "clean",
        "source_format": "docx",
        "images": 2,
    }
    base.update(overrides)
    return base


@pytest.fixture
def docx_file(tmp_path: Path) -> Path:
    p = tmp_path / "memo.docx"
    p.write_bytes(DOCX_BYTES)
    return p


def _error_payload(exc: pytest.ExceptionInfo[ToolError]) -> dict[str, object]:
    return json.loads(str(exc.value))


# ----------------- read side -----------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_list_and_meta_accept_office_doc(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    item = asset_meta(slug="memo", kind="office_doc")
    respx_mock.get(f"{ICS}/api/assets/index").mock(
        return_value=httpx.Response(200, json={"items": [item], "next_cursor": None})
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/memo/meta").mock(
        return_value=httpx.Response(200, json=item)
    )
    listing = await call_tool(mcp, "ics_assets_list", {"kind": ["office_doc"]})
    assert listing["items"][0]["kind"] == "office_doc"
    meta = await call_tool(mcp, "ics_asset_meta", {"slug_or_id": "memo"})
    assert meta["kind"] == "office_doc"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_outline_passes_office_shape_through(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    outline = {
        "kind": "office_doc",
        "title": "memo",
        "source_format": "odt",
        "images": 0,
        "headings": [{"level": 2, "text": "Budget", "line": 5}],
        "line_count": 12,
        "truncated": False,
    }
    respx_mock.get(f"{ICS}/api/assets/by-slug/memo/outline").mock(
        return_value=httpx.Response(200, json=outline)
    )
    payload = await call_tool(mcp, "ics_asset_outline", {"slug_or_id": "memo"})
    assert payload["source_format"] == "odt"
    assert payload["headings"][0]["line"] == 5


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_read_returns_office_markdown_with_extra_fields(real_client, respx_mock, make_mcp):
    mcp = make_mcp(read)
    content = "# memo\n\n## Budget\n\n| Item | Cost |\n| --- | --- |\n| A | 1 |\n\n*[image]*\n"
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/memo/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "memo",
                "path": "memo.docx",
                "content": content,
                "total_lines": 9,
                "returned_range": [1, 9],
                "version": 1,
                "current_version": 1,
                "format": "markdown",
                "source_format": "docx",
                "images": 1,
            },
        )
    )
    payload = await call_tool(mcp, "ics_asset_read", {"slug_or_id": "memo", "lines": "1-9"})
    assert route.calls[0].request.url.params["lines"] == "1-9"
    assert payload["format"] == "markdown"
    assert payload["source_format"] == "docx"
    assert payload["images"] == 1
    assert "*[image]*" in payload["content"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_resource_inlines_office_markdown(real_client, respx_mock, make_mcp):
    mcp = make_mcp(resources_mod)
    respx_mock.get(f"{ICS}/api/assets/by-slug/memo/meta").mock(
        return_value=httpx.Response(200, json={"id": "x", "slug": "memo", "kind": "office_doc"})
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/memo/file-mcp").mock(
        return_value=httpx.Response(200, json={"content": "# memo\n\n## Budget\n"})
    )
    result = await read_resource(mcp, "ics://asset/memo")
    data = json.loads(result.contents[0].text)
    assert data["content"].startswith("# memo")


# ----------------- ics_asset_create_document -----------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_document_uploads_multipart_with_query_params(
    real_client, respx_mock, make_mcp, docx_file
):
    mcp = make_mcp(write_documents)
    project_id = "00000000-0000-0000-0000-000000000003"
    route = respx_mock.post(f"{ICS}/api/assets/document").mock(
        return_value=httpx.Response(201, json=create_document_response())
    )
    rename = respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}")
    payload = await call_tool(
        mcp,
        "ics_asset_create_document",
        {
            "payload": {
                "file_path": str(docx_file),
                "share_mode": "public",
                "project_id": project_id,
            },
            "confirm": True,
        },
    )
    request = route.calls[0].request
    assert request.url.params["share_mode"] == "public"
    assert request.url.params["project_id"] == project_id
    body = request.content
    assert b'name="file"; filename="memo.docx"' in body
    assert f"Content-Type: {DOCX_MIME}".encode() in body
    assert DOCX_BYTES in body
    assert rename.call_count == 0
    assert payload["slug"] == "memo"
    assert payload["source_format"] == "docx"
    assert payload["images"] == 2
    assert payload["kind"] == "office_doc"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_document_accepts_legacy_doc_with_title_and_tags(
    real_client, respx_mock, make_mcp, tmp_path
):
    mcp = make_mcp(write_documents)
    doc = tmp_path / "Old Memo.DOC"
    doc.write_bytes(DOC_BYTES)
    route = respx_mock.post(f"{ICS}/api/assets/document").mock(
        return_value=httpx.Response(
            201, json=create_document_response(title="Old Memo", source_format="doc", images=0)
        )
    )
    rename = respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "title": "Memo 1999"})
    )
    tags = respx_mock.put(f"{ICS}/api/assets/{ASSET_ID}/tags").mock(
        return_value=httpx.Response(200, json={"tags": ["archive"]})
    )
    payload = await call_tool(
        mcp,
        "ics_asset_create_document",
        {"payload": {"file_path": str(doc), "title": "Memo 1999", "tags": ["archive"]}},
    )
    body = route.calls[0].request.content
    # The extension is lowercased for ICS, the stem is kept as named.
    assert b'filename="Old Memo.doc"' in body
    assert b"Content-Type: application/msword" in body
    assert json.loads(rename.calls[0].request.content) == {"title": "Memo 1999"}
    assert json.loads(tags.calls[0].request.content) == {"tags": ["archive"]}
    assert payload["title"] == "Memo 1999"
    assert payload["source_format"] == "doc"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_document_rejects_file_without_signature(
    real_client, respx_mock, make_mcp, tmp_path
):
    mcp = make_mcp(write_documents)
    fake = tmp_path / "fake.docx"
    fake.write_bytes(b"{\\rtf1 not a docx}")
    route = respx_mock.post(f"{ICS}/api/assets/document")
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_create_document", {"payload": {"file_path": str(fake)}})
    err = _error_payload(exc)
    assert err["code"] == "invalid_office_document"
    assert "hint" in err
    assert route.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("sheet.xlsx", "document_file_required"),
        # The extension picks the kind: Word bytes named .pdf are no PDF.
        ("report.pdf", "invalid_pdf"),
        ("missing.odt", "invalid_argument"),
    ],
)
async def test_create_document_rejects_bad_path(real_client, make_mcp, tmp_path, name, code):
    mcp = make_mcp(write_documents)
    target = tmp_path / name
    if not name.startswith("missing"):
        target.write_bytes(DOCX_BYTES)
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_create_document", {"payload": {"file_path": str(target)}})
    assert _error_payload(exc)["code"] == code


@pytest.mark.asyncio
async def test_create_document_refuses_file_path_over_http(
    real_client, make_mcp, docx_file, monkeypatch
):
    monkeypatch.setattr(get_settings(), "mcp_transport", "http")
    mcp = make_mcp(write_documents)
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp, "ics_asset_create_document", {"payload": {"file_path": str(docx_file)}}
        )
    assert _error_payload(exc)["code"] == "invalid_argument"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "office_file_required"),
        (400, "invalid_office_document"),
        (400, "office_encrypted"),
        (400, "office_conversion_failed"),
        (413, "office_too_large"),
        (413, "storage_quota_exceeded"),
    ],
)
@respx.mock(assert_all_called=False)
async def test_create_document_promotes_backend_office_code(
    real_client, respx_mock, make_mcp, docx_file, status, code
):
    mcp = make_mcp(write_documents)
    respx_mock.post(f"{ICS}/api/assets/document").mock(
        return_value=httpx.Response(status, json={"detail": "Rejected", "code": code})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp, "ics_asset_create_document", {"payload": {"file_path": str(docx_file)}}
        )
    err = _error_payload(exc)
    assert err["code"] == code
    assert err["status"] == status
    assert err["hint"] == write_office.OFFICE_HINTS[code]


# ----------------- ics_asset_replace_document -----------------


def _mock_office_meta(respx_mock, kind: str = "office_doc"):
    return respx_mock.get(f"{ICS}/api/assets/by-slug/memo/meta").mock(
        return_value=httpx.Response(200, json=asset_meta(slug="memo", kind=kind))
    )


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_replace_document_posts_one_file_in_files_field(
    real_client, respx_mock, make_mcp, tmp_path
):
    mcp = make_mcp(write_documents, session_tool)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    _mock_office_meta(respx_mock)
    odt = tmp_path / "memo.odt"
    odt.write_bytes(DOCX_BYTES)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions").mock(
        return_value=httpx.Response(201, json={"id": ASSET_ID, "version": 2})
    )
    payload = await call_tool(
        mcp, "ics_asset_replace_document", {"slug_or_id": "memo", "file_path": str(odt)}
    )
    body = route.calls[0].request.content
    assert body.count(b'name="files"') == 1
    assert b'filename="memo.odt"' in body
    assert b"Content-Type: application/vnd.oasis.opendocument.text" in body
    assert payload["version"] == 2


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_replace_document_dry_run_sends_nothing(real_client, respx_mock, make_mcp, docx_file):
    mcp = make_mcp(write_documents, session_tool)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions")
    payload = await call_tool(
        mcp, "ics_asset_replace_document", {"slug_or_id": "memo", "file_path": str(docx_file)}
    )
    assert route.call_count == 0
    assert payload["action"] == "replace_document"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_replace_document_keeps_the_asset_kind(real_client, respx_mock, make_mcp, docx_file):
    """A PDF asset takes only a PDF as its next version."""
    mcp = make_mcp(write_documents)
    _mock_office_meta(respx_mock, kind="pdf_doc")
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions")
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_replace_document",
            {"slug_or_id": "memo", "file_path": str(docx_file), "confirm": True},
        )
    assert _error_payload(exc)["code"] == "pdf_file_required"
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_replace_document_promotes_encrypted(real_client, respx_mock, make_mcp, docx_file):
    mcp = make_mcp(write_documents)
    _mock_office_meta(respx_mock)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions").mock(
        return_value=httpx.Response(
            400, json={"detail": "Password protected", "code": "office_encrypted"}
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_replace_document",
            {"slug_or_id": "memo", "file_path": str(docx_file), "confirm": True},
        )
    assert _error_payload(exc)["code"] == "office_encrypted"
