"""Publication wire contract and receipt confirmation from the real MCP boundary."""

from __future__ import annotations

import json
from email.parser import BytesParser
from email.policy import default

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp.server import build_mcp
from ics_mcp.tools import write_documents, write_html, write_versions
from tests.conftest import ASSET_ID, ICS, asset_meta, call_tool

PUBLICATION = {"id": "publication-2354", "order_id": "delivery-17", "role": "report"}
PROJECT = "12345678-1234-5678-1234-567812345679"
HTML = {
    "id": ASSET_ID,
    "slug": "confirmed-report",
    "title": "Report",
    "kind": "html_bundle",
    "entry_path": "index.html",
    "file_count": 1,
    "size_bytes": 16,
    "security_status": "clean",
}
VERSION = {
    "id": ASSET_ID,
    "version": 6,
    "entry_path": "index.html",
    "file_count": 1,
    "size_bytes": 16,
    "security_status": "clean",
}


def receipt(result, *, version=1, project_id=None):
    return {
        "publication_id": "publication-2354",
        "project_id": project_id,
        "order_id": "delivery-17",
        "role": "report",
        "schema_version": 1,
        "payload_hash": "a" * 64,
        "asset_id": ASSET_ID,
        "version": version,
        "result": result,
    }


def html_args(*, publication=True):
    payload = {
        "title": "Report",
        "entry_path": "index.html",
        "files": [{"path": "index.html", "content_text": "<h1>Report</h1>"}],
    }
    if publication:
        payload["publication"] = PUBLICATION
    return {"payload": payload}


def form_fields(request):
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode() + request.content
    )
    return {
        part.get_param("name", header="content-disposition"): part.get_payload(decode=True).decode()
        for part in message.iter_parts()
        if part.get_filename() is None
    }


def lookup(respx_mock, payload):
    return respx_mock.get(f"{ICS}/api/assets/publications/publication-2354").respond(
        200, json=payload
    )


@respx.mock
async def test_create_html_confirms_receipt_instead_of_inventing_version(
    real_client, respx_mock, make_mcp
):
    mcp = make_mcp(write_html)
    post = respx_mock.post(f"{ICS}/api/assets/html-json").respond(201, json=HTML)
    get = lookup(respx_mock, receipt(HTML))
    result = await call_tool(mcp, "ics_asset_create_html", html_args())
    assert json.loads(post.calls[0].request.content)["publication"] == PUBLICATION
    assert result["id"] == ASSET_ID
    assert result["version"] == 1
    assert result["publication_receipt"] == receipt(HTML)
    assert dict(get.calls[0].request.url.params) == {"order_id": "delivery-17", "role": "report"}
    assert post.call_count == 1


@pytest.mark.parametrize("kind", ["markdown", "html", "pdf", "office"])
@respx.mock
async def test_whole_version_sends_identity_and_returns_historical_receipt(
    real_client, respx_mock, make_mcp, tmp_path, kind
):
    mcp = make_mcp(write_html, write_versions, write_documents)
    meta_kind = {
        "markdown": "md_single",
        "html": "html_bundle",
        "pdf": "pdf_doc",
        "office": "office_doc",
    }[kind]
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").respond(
        200, json=asset_meta(version=99, kind=meta_kind, project_id=PROJECT)
    )
    args = {"slug_or_id": "abc", "publication": PUBLICATION, "expected_version": 5, "confirm": True}
    if kind == "markdown":
        tool = "ics_asset_new_version"
        args["files"] = [{"path": "index.md", "content": "Report"}]
    elif kind == "html":
        tool = "ics_asset_html_replace_bundle"
        args.update(
            entry_path="index.html", files=[{"path": "index.html", "content_text": "Report"}]
        )
    else:
        tool = "ics_asset_replace_document"
        file = tmp_path / ("report.pdf" if kind == "pdf" else "report.docx")
        file.write_bytes(b"%PDF-1.7\n" if kind == "pdf" else b"PK\x03\x04test")
        args["file_path"] = str(file)
    post = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions").respond(201, json=VERSION)
    get = lookup(respx_mock, receipt(VERSION, version=6, project_id=PROJECT))
    result = await call_tool(mcp, tool, args)
    fields = form_fields(post.calls[0].request)
    assert json.loads(fields["publication"]) == PUBLICATION
    assert fields["expected_version"] == "5"
    assert result["version"] == 6
    assert result["publication_receipt"]["version"] == 6
    assert dict(get.calls[0].request.url.params) == {
        "order_id": "delivery-17",
        "role": "report",
        "project_id": PROJECT,
    }
    assert post.call_count == 1


@respx.mock
async def test_keyed_replacement_requires_expected_version_before_any_upload(
    real_client, respx_mock, make_mcp
):
    mcp = make_mcp(write_versions)
    with pytest.raises(ToolError) as caught:
        await call_tool(
            mcp,
            "ics_asset_new_version",
            {
                "slug_or_id": "abc",
                "files": [{"path": "a.md", "content": "x"}],
                "publication": PUBLICATION,
                "confirm": True,
            },
        )
    error = json.loads(str(caught.value))
    assert error["code"] == "invalid_argument"
    assert error["field"] == "expected_version"
    assert not respx_mock.calls


@respx.mock
async def test_receipt_read_uses_original_scope_without_mutation(real_client, respx_mock):
    get = lookup(respx_mock, receipt(VERSION, version=6, project_id=PROJECT))
    result = await call_tool(
        build_mcp(), "ics_publication_get", {"publication": PUBLICATION, "project_id": PROJECT}
    )
    assert result == receipt(VERSION, version=6, project_id=PROJECT)
    assert dict(get.calls[0].request.url.params) == {
        "order_id": "delivery-17",
        "role": "report",
        "project_id": PROJECT,
    }
    assert [call.request.method for call in respx_mock.calls] == ["GET"]


@pytest.mark.parametrize("failure", ["timeout", 502, 503, 504])
@respx.mock
async def test_ambiguous_create_preserves_identity_and_never_reposts(
    real_client, respx_mock, make_mcp, failure
):
    post = respx_mock.post(f"{ICS}/api/assets/html-json")
    if failure == "timeout":
        post.side_effect = httpx.ReadTimeout("lost acknowledgement")
    else:
        post.respond(failure, json={"detail": "gateway failure"})
    with pytest.raises(ToolError) as caught:
        await call_tool(make_mcp(write_html), "ics_asset_create_html", html_args())
    error = json.loads(str(caught.value))
    assert error["data"]["outcome"] == "unknown"
    assert error["data"]["publication"] == PUBLICATION
    assert error["data"]["project_id"] is None
    assert post.call_count == 1


@pytest.mark.parametrize(
    "bad_receipt", ["missing", "wrong_identity", "wrong_asset", "wrong_result", "malformed_version"]
)
@respx.mock
async def test_successful_post_without_matching_receipt_cannot_claim_confirmation(
    real_client, respx_mock, make_mcp, bad_receipt
):
    post = respx_mock.post(f"{ICS}/api/assets/html-json").respond(201, json=HTML)
    data = receipt(HTML)
    if bad_receipt == "missing":
        respx_mock.get(f"{ICS}/api/assets/publications/publication-2354").respond(
            404, json={"code": "publication_not_found", "detail": "publication not found"}
        )
    else:
        if bad_receipt == "wrong_identity":
            data["publication_id"] = "another-operation"
        elif bad_receipt == "wrong_asset":
            data["asset_id"] = PROJECT
        elif bad_receipt == "wrong_result":
            data["result"] = {**HTML, "slug": "another-result"}
        else:
            data["version"] = 0
        lookup(respx_mock, data)
    with pytest.raises(ToolError) as caught:
        await call_tool(make_mcp(write_html), "ics_asset_create_html", html_args())
    error = json.loads(str(caught.value))
    assert error["code"] == "publication_unconfirmed"
    assert error["data"]["outcome"] == "unknown"
    assert error["data"]["publication"] == PUBLICATION
    assert error["data"]["result"]["id"] == ASSET_ID
    assert post.call_count == 1


@respx.mock
async def test_legacy_create_does_not_send_or_look_up_publication(
    real_client, respx_mock, make_mcp
):
    post = respx_mock.post(f"{ICS}/api/assets/html-json").respond(201, json=HTML)
    result = await call_tool(
        make_mcp(write_html), "ics_asset_create_html", html_args(publication=False)
    )
    assert result == HTML
    assert "publication" not in json.loads(post.calls[0].request.content)
    assert len(respx_mock.calls) == 1


@pytest.mark.parametrize(
    "tool,args",
    [
        (
            "ics_asset_html_replace_bundle",
            {"entry_path": "index.html", "files": [{"path": "index.html", "content_text": "x"}]},
        ),
        ("ics_asset_replace_document", {"file_path": "missing.pdf"}),
    ],
)
@respx.mock
async def test_other_keyed_replacements_require_a_caller_version(
    real_client, respx_mock, make_mcp, tool, args
):
    with pytest.raises(ToolError) as caught:
        await call_tool(
            make_mcp(write_html, write_documents),
            tool,
            {"slug_or_id": "abc", "publication": PUBLICATION, "confirm": True, **args},
        )
    assert json.loads(str(caught.value))["field"] == "expected_version"
    assert not respx_mock.calls


@pytest.mark.parametrize("code", ["publication_conflict", "version_conflict"])
@respx.mock
async def test_explicit_conflict_remains_a_refusal_without_receipt_retry(
    real_client, respx_mock, make_mcp, code
):
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").respond(200, json=asset_meta())
    post = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions").respond(
        409, json={"code": code, "detail": "Conflict", "field": "expected_version"}
    )
    with pytest.raises(ToolError) as caught:
        await call_tool(
            make_mcp(write_versions),
            "ics_asset_new_version",
            {
                "slug_or_id": "abc",
                "files": [{"path": "a.md", "content": "x"}],
                "publication": PUBLICATION,
                "expected_version": 1,
                "confirm": True,
            },
        )
    error = json.loads(str(caught.value))
    assert error["code"] == code
    assert error["status"] == 409
    assert error["field"] == "expected_version"
    assert post.call_count == 1
    assert len(respx_mock.calls) == 2


@respx.mock
async def test_missing_receipt_is_inconclusive_and_read_only(real_client, respx_mock):
    route = respx_mock.get(f"{ICS}/api/assets/publications/publication-2354").respond(
        404, json={"code": "publication_not_found", "detail": "Not found"}
    )
    with pytest.raises(ToolError) as caught:
        await call_tool(build_mcp(), "ics_publication_get", {"publication": PUBLICATION})
    error = json.loads(str(caught.value))
    assert error["code"] == "publication_not_found"
    assert error["data"]["outcome"] == "unknown"
    assert error["data"]["publication"] == PUBLICATION
    assert route.call_count == 1
    assert [call.request.method for call in respx_mock.calls] == ["GET"]


@pytest.mark.parametrize(
    "publication",
    [
        {**PUBLICATION, "id": "bad/key"},
        {**PUBLICATION, "role": "bad role"},
        {**PUBLICATION, "principal": "other-user"},
    ],
)
@respx.mock
async def test_invalid_publication_never_reaches_http(real_client, respx_mock, publication):
    args = html_args()
    args["payload"]["publication"] = publication
    with pytest.raises(ToolError):
        await call_tool(build_mcp(), "ics_asset_create_html", args)
    assert not respx_mock.calls


async def test_publication_protocol_schema_and_unknown_help():
    tools = {tool.name: tool for tool in await build_mcp().list_tools()}
    read = tools["ics_publication_get"]
    assert read.annotations.readOnlyHint
    assert read.annotations.idempotentHint
    assert "unknown" in read.description
    for name in [
        "ics_asset_new_version",
        "ics_asset_html_replace_bundle",
        "ics_asset_replace_document",
    ]:
        tool = tools[name]
        assert "publication" in tool.parameters["properties"]
        assert "publication" not in tool.parameters.get("required", [])
        assert "expected_version" in tool.description
        assert "unknown" in tool.description
    create = tools["ics_asset_create_html"]
    assert "publication_receipt" in str(create.output_schema)


@respx.mock
async def test_uuid_metadata_requires_original_project_scope_before_keyed_post(
    real_client, respx_mock, make_mcp
):
    # An ICS without `/by-id/{id}/meta` answers a bare 404; its UUID endpoint
    # deliberately returns a smaller shape than /meta.
    respx_mock.get(f"{ICS}/api/assets/by-id/{ASSET_ID}/meta").respond(
        404, json={"detail": "Not Found"}
    )
    respx_mock.get(f"{ICS}/api/assets/{ASSET_ID}").respond(
        200, json={"id": ASSET_ID, "slug": "abc", "kind": "md_single", "version": 5}
    )
    meta = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").respond(
        200, json=asset_meta(project_id=PROJECT)
    )
    post = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions").respond(201, json=VERSION)
    get = lookup(respx_mock, receipt(VERSION, version=6, project_id=PROJECT))
    result = await call_tool(
        make_mcp(write_versions),
        "ics_asset_new_version",
        {
            "slug_or_id": ASSET_ID,
            "files": [{"path": "a.md", "content": "x"}],
            "expected_version": 5,
            "publication": PUBLICATION,
            "confirm": True,
        },
    )
    assert meta.call_count == post.call_count == get.call_count == 1
    assert result["publication_receipt"]["project_id"] == PROJECT
    assert [call.request.method for call in respx_mock.calls] == [
        "GET",
        "GET",
        "GET",
        "POST",
        "GET",
    ]


@respx.mock
async def test_uuid_meta_route_carries_the_project_scope(real_client, respx_mock, make_mcp):
    meta = respx_mock.get(f"{ICS}/api/assets/by-id/{ASSET_ID}/meta").respond(
        200, json=asset_meta(project_id=PROJECT)
    )
    post = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions").respond(201, json=VERSION)
    lookup(respx_mock, receipt(VERSION, version=6, project_id=PROJECT))
    result = await call_tool(
        make_mcp(write_versions),
        "ics_asset_new_version",
        {
            "slug_or_id": ASSET_ID,
            "files": [{"path": "a.md", "content": "x"}],
            "expected_version": 5,
            "publication": PUBLICATION,
            "confirm": True,
        },
    )
    assert meta.call_count == post.call_count == 1
    assert result["publication_receipt"]["project_id"] == PROJECT
    assert [call.request.method for call in respx_mock.calls] == ["GET", "POST", "GET"]


@respx.mock
async def test_missing_scope_is_not_guessed_as_unscoped_before_post(
    real_client, respx_mock, make_mcp
):
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").respond(
        200, json={"id": ASSET_ID, "slug": "abc", "kind": "md_single", "version": 5}
    )
    with pytest.raises(ToolError) as caught:
        await call_tool(
            make_mcp(write_versions),
            "ics_asset_new_version",
            {
                "slug_or_id": "abc",
                "files": [{"path": "a.md", "content": "x"}],
                "expected_version": 5,
                "publication": PUBLICATION,
                "confirm": True,
            },
        )
    assert json.loads(str(caught.value))["code"] == "invalid_response"
    assert all(call.request.method == "GET" for call in respx_mock.calls)
