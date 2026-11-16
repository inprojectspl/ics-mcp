"""CAS tool contract matches ICS docs/expected-version-api.md (#2351).

The real MCP tools and ICSClient serialize each request to a mocked HTTP
endpoint. The metadata version deliberately differs from the caller's basis.
"""

from __future__ import annotations

import json
from email.parser import BytesParser
from email.policy import default

import pytest
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError

from ics_mcp.server import build_mcp
from ics_mcp.tools import write_documents, write_html, write_md, write_versions
from tests.conftest import ASSET_ID, ICS, asset_meta, call_tool

CASES = [
    ("update_content", "PUT", "/content", "json", {"content": "changed", "path": "a.md"}),
    ("add_file", "POST", "/files", "form", {"path": "b.md", "content": "new"}),
    ("create_empty_file", "POST", "/files/empty", "json", {"path": "empty.md"}),
    ("move_file", "PATCH", "/files/move", "json", {"from_path": "a.md", "to_path": "b.md"}),
    ("delete_file", "DELETE", "/files", "query", {"path": "a.md"}),
    (
        "new_version",
        "POST",
        "/versions",
        "form",
        {"files": [{"path": "a.md", "content": "new"}], "entry_path": "a.md"},
    ),
    ("restore_version", "POST", "/versions/2/restore", "query", {"version": 2}),
    (
        "html_replace_bundle",
        "POST",
        "/versions",
        "form",
        {
            "entry_path": "index.html",
            "files": [{"path": "index.html", "content_text": "<p>new</p>"}],
        },
    ),
    ("replace_document", "POST", "/versions", "form", {"file_path": "source.pdf"}),
    ("replace_document", "POST", "/versions", "form", {"file_path": "source.docx"}),
]
TOOL_NAMES = sorted({f"ics_asset_{case[0]}" for case in CASES})


def tool_args(case, tmp_path):
    name, _, _, _, values = case
    args = {"slug_or_id": "abc", **values}
    if name not in {"add_file", "create_empty_file"}:
        args["confirm"] = True
    if "file_path" in args:
        path = tmp_path / args["file_path"]
        path.write_bytes(b"%PDF-1.7\n" if path.suffix == ".pdf" else b"PK\x03\x04test")
        args["file_path"] = str(path)
    return args


def wire_fields(request, location):
    if location == "json":
        return json.loads(request.content)
    if location == "query":
        return dict(request.url.params)
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode() + request.content
    )
    return {
        part.get_param("name", header="content-disposition"): part.get_payload(decode=True).decode()
        for part in message.iter_parts()
        if part.get_filename() is None
    }


def resolve(respx_mock, args):
    kind = "office_doc" if args.get("file_path", "").endswith(".docx") else "pdf_doc"
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").respond(
        200, json=asset_meta(version=99, kind=kind)
    )


@pytest.mark.parametrize(
    "case", CASES, ids=lambda case: f"{case[0]}-{case[4].get('file_path', '')}"
)
@pytest.mark.parametrize("mode", ["expected", "omitted", "null"])
@respx.mock
async def test_expected_version_wire_and_legacy(
    real_client, respx_mock, make_mcp, tmp_path, case, mode
):
    mcp = make_mcp(write_md, write_versions, write_html, write_documents)
    name, method, endpoint, location, _ = case
    args = tool_args(case, tmp_path)
    resolve(respx_mock, args)
    if mode != "omitted":
        args["expected_version"] = 5 if mode == "expected" else None
    route = respx_mock.route(method=method, path=f"/api/assets/{ASSET_ID}{endpoint}").respond(
        200, json={"version": 6, "slug": "abc"}
    )
    result = await call_tool(mcp, f"ics_asset_{name}", args)
    assert result == {"version": 6, "slug": "abc"}
    assert route.call_count == 1
    request = route.calls[0].request
    fields = wire_fields(request, location)
    if mode == "expected":
        assert fields["expected_version"] == (5 if location == "json" else "5")
    else:
        assert "expected_version" not in fields
    if location != "query":
        assert "expected_version" not in request.url.params
    if location == "query":
        assert request.content == b""


@pytest.mark.parametrize(
    "case", CASES, ids=lambda case: f"{case[0]}-{case[4].get('file_path', '')}"
)
@respx.mock
async def test_version_conflict_is_machine_readable_without_retry(
    real_client, respx_mock, make_mcp, tmp_path, case
):
    mcp = make_mcp(write_md, write_versions, write_html, write_documents)
    name, method, endpoint, location, _ = case
    args = {**tool_args(case, tmp_path), "expected_version": 5}
    resolve(respx_mock, args)
    route = respx_mock.route(method=method, path=f"/api/assets/{ASSET_ID}{endpoint}").respond(
        409,
        json={
            "code": "version_conflict",
            "detail": "Asset version changed.",
            "field": "expected_version",
        },
    )
    async with Client(mcp) as client:
        result = await client.call_tool(f"ics_asset_{name}", args, raise_on_error=False)
    assert result.is_error
    error = json.loads(result.content[0].text)
    assert error["code"] == "version_conflict"
    assert error["field"] == "expected_version"
    assert error["status"] == 409
    assert route.call_count == 1
    assert wire_fields(route.calls[0].request, location)["expected_version"] == (
        5 if location == "json" else "5"
    )


async def test_expected_version_protocol_schema_and_help(settings):
    mcp = build_mcp(settings)
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    for name in TOOL_NAMES:
        schema = tools[name].parameters
        field = schema["properties"]["expected_version"]
        assert "expected_version" not in schema.get("required", [])
        # CompactCatalog removes null/default from optional public arguments.
        # Omission and explicit null are exercised on the wire above.
        assert field["type"] == "integer"
        assert field["minimum"] == 1
        assert "version_conflict" in field["description"]
        assert "expected_version" in tools[name].description
    help_result = await call_tool(mcp, "ics_help", {"topic": "tools"})
    assert "expected_version" in help_result["content_markdown"]
    assert "version_conflict" in help_result["content_markdown"]


@pytest.mark.parametrize("bad", [0, -1, 1.5, True])
@respx.mock
async def test_invalid_expected_version_refuses_before_http(real_client, respx_mock, settings, bad):
    mcp = build_mcp(settings)
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_update_content",
            {"slug_or_id": "abc", "content": "new", "expected_version": bad, "confirm": True},
        )
    error = json.loads(str(exc.value))
    assert error["code"] == "invalid_argument"
    assert error["field"] == "expected_version"
    assert not respx_mock.calls
