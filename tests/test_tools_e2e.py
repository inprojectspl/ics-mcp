"""End-to-end tool tests against a fake ICS (respx).

Each test wires a real `ICSClient` to a respx-mocked ICS via the
`real_client` conftest fixture, invokes the tool body directly, and
asserts the structured payload returned to the agent.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from ics_mcp.tools import (
    discovery,
    read,
    share,
    write_html,
    write_md,
)
from ics_mcp.tools import (
    session as session_tool,
)
from tests.conftest import (
    ASSET_ID,
    ICS,
    asset_meta,
    call_tool,
    create_md_response,
    mock_resolve,
)

# ============================================================
#  Discovery
# ============================================================


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_assets_list_passes_filters_and_parses(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    respx_mock.get(f"{ICS}/api/assets/index").mock(
        return_value=httpx.Response(
            200,
            json={"items": [asset_meta(pinned=True, tags=["x"])], "next_cursor": None},
        )
    )
    payload = await call_tool(mcp, "ics_assets_list", {"kind": ["md_single"], "limit": 10})
    assert payload["count"] == 1
    assert payload["items"][0]["slug"] == "abc"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_meta_with_slug(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").mock(
        return_value=httpx.Response(200, json=asset_meta())
    )
    payload = await call_tool(mcp, "ics_asset_meta", {"slug_or_id": "abc"})
    assert payload["slug"] == "abc"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_assets_search_returns_snippets(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    respx_mock.get(f"{ICS}/api/assets/search-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": ASSET_ID,
                        "slug": "abc",
                        "title": "T",
                        "kind": "md_single",
                        "score": 0.5,
                        "snippets": [{"path": None, "line": None, "text": "...<em>hit</em>..."}],
                    }
                ],
                "total": 1,
                "offset": 0,
                "limit": 20,
                "has_more": False,
            },
        )
    )
    payload = await call_tool(mcp, "ics_assets_search", {"q": "hit"})
    assert payload["total"] == 1
    assert "hit" in payload["items"][0]["snippets"][0]["text"]


SEARCH_HIT = {
    "id": ASSET_ID,
    "slug": "spec-v1",
    "title": "Spec v1",
    "kind": "md_single",
    "score": 0.6000000238418579,
    "summary": "First version of the account API. " * 6,
    "doc_type": "specification",
    "freshness": "superseded",
    "latest": "spec-v3",
    "estimated_tokens": 640,
    "snippets": [
        {
            "path": "Spec v1.md",
            "line": 7,
            "text": "no <em>SSO</em> yet.\n\n- `GET /api/v1/invoices`",
            "page": None,
        }
    ],
}


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_assets_search_compact_hits(real_client, respx_mock, make_mcp):
    """Hits look like list items: no id, no score, no nulls, plain snippets."""
    mcp = make_mcp(discovery)
    current = {**SEARCH_HIT, "slug": "spec-v3", "freshness": "current", "latest": None}
    respx_mock.get(f"{ICS}/api/assets/search-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [SEARCH_HIT, current],
                "total": 5,
                "offset": 0,
                "limit": 2,
                "has_more": True,
            },
        )
    )
    payload = await call_tool(mcp, "ics_assets_search", {"q": "sso", "limit": 2})
    first, second = payload["items"]
    assert set(first) == {
        "slug",
        "title",
        "doc_type",
        "freshness",
        "summary",
        "estimated_tokens",
        "latest",
        "snippets",
    }
    assert first["latest"] == "spec-v3"
    assert len(first["summary"]) <= 120
    assert first["snippets"] == [{"text": "no SSO yet. - `GET /api/v1/invoices`", "line": 7}]
    assert "freshness" not in second and "latest" not in second
    assert payload["total"] == 5
    assert payload["next_offset"] == 2


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_assets_search_full_detail_is_the_ics_hit(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    body = {"items": [SEARCH_HIT], "total": 1, "offset": 0, "limit": 20, "has_more": False}
    respx_mock.get(f"{ICS}/api/assets/search-mcp").mock(return_value=httpx.Response(200, json=body))
    payload = await call_tool(mcp, "ics_assets_search", {"q": "sso", "detail": "full"})
    assert payload == body


# ============================================================
#  Read
# ============================================================


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_read_returns_content_with_range(real_client, respx_mock, make_mcp):
    mcp = make_mcp(read)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "abc",
                "path": "index.md",
                "content": "Hello\nWorld",
                "total_lines": 2,
                "returned_range": [1, 2],
            },
        )
    )
    payload = await call_tool(mcp, "ics_asset_read", {"slug_or_id": "abc", "lines": "1-2"})
    assert payload["total_lines"] == 2
    assert "Hello" in payload["content"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_read_bundle_file_by_path(real_client, respx_mock, make_mcp):
    """html_bundle: `path` goes to the query, a text file comes back like md."""
    mcp = make_mcp(read)
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "abc",
                "path": "assets/style.css",
                "content": "body { color: red; }",
                "total_lines": 1,
                "returned_range": [1, 1],
            },
        )
    )
    payload = await call_tool(
        mcp, "ics_asset_read", {"slug_or_id": "abc", "path": "assets/style.css"}
    )
    assert payload["content"] == "body { color: red; }"
    assert route.calls[0].request.url.params["path"] == "assets/style.css"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_read_markdown_format_and_max_lines_passthrough(
    real_client, respx_mock, make_mcp
):
    """`format` and `max_lines` go to the query; the response carries `format`."""
    mcp = make_mcp(read)
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "abc",
                "path": "index.html",
                "content": "# Title\n\nParagraph.",
                "total_lines": 3,
                "returned_range": [1, 3],
                "format": "markdown",
            },
        )
    )
    payload = await call_tool(
        mcp,
        "ics_asset_read",
        {"slug_or_id": "abc", "format": "markdown", "max_lines": 5000},
    )
    assert payload["format"] == "markdown"
    assert payload["content"].startswith("# Title")
    params = route.calls[0].request.url.params
    assert params["format"] == "markdown"
    assert params["max_lines"] == "5000"
    assert params["lines"] == "1-5000"
    assert payload["truncated"] is False


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_read_max_lines_returns_the_first_lines(real_client, respx_mock, make_mcp):
    """`max_lines` smaller than the file gives the head with `truncated`, not
    `file_too_large` (ICS clamps `lines` to the file)."""
    mcp = make_mcp(read)
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "abc",
                "path": "a.md",
                "content": "1\n2\n3\n4\n5",
                "total_lines": 11,
                "returned_range": [1, 5],
            },
        )
    )
    payload = await call_tool(mcp, "ics_asset_read", {"slug_or_id": "abc", "max_lines": 5})
    assert payload["truncated"] is True
    assert route.calls[0].request.url.params["lines"] == "1-5"
    # With an explicit range `max_lines` only raises the cap.
    await call_tool(mcp, "ics_asset_read", {"slug_or_id": "abc", "lines": "3-4", "max_lines": 5})
    assert route.calls[1].request.url.params["lines"] == "3-4"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_read_bundle_binary_base64(real_client, respx_mock, make_mcp):
    """`encoding=base64` goes to the query; a binary response validates without `content`."""
    mcp = make_mcp(read)
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "abc",
                "path": "img/logo.png",
                "content_base64": "iVBORw0KGgo=",
                "mime": "image/png",
                "size_bytes": 8,
                "encoding": "base64",
            },
        )
    )
    payload = await call_tool(
        mcp,
        "ics_asset_read",
        {"slug_or_id": "abc", "path": "img/logo.png", "encoding": "base64"},
    )
    assert payload["content_base64"] == "iVBORw0KGgo="
    assert payload["mime"] == "image/png"
    assert "content" not in payload
    assert route.calls[0].request.url.params["encoding"] == "base64"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_read_bundle_binary_without_flag_maps_415(real_client, respx_mock, make_mcp):
    mcp = make_mcp(read)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/file-mcp").mock(
        return_value=httpx.Response(
            415,
            json={
                "detail": {
                    "code": "binary_file",
                    "mime": "font/woff2",
                    "size_bytes": 12345,
                    "hint": "binary file, use encoding=base64",
                }
            },
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_read", {"slug_or_id": "abc", "path": "f.woff2"})
    msg = str(exc.value)
    assert "unsupported_media_type" in msg
    assert "binary_file" in msg


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_read_bundle_over_cap_maps_413(real_client, respx_mock, make_mcp):
    mcp = make_mcp(read)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/file-mcp").mock(
        return_value=httpx.Response(
            413, json={"detail": "binary file too large for base64 (size=2097152, max=1048576)"}
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_read",
            {"slug_or_id": "abc", "path": "big.png", "encoding": "base64"},
        )
    assert "payload_too_large" in str(exc.value)


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_list_files_returns_inventory(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/files-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "abc",
                "kind": "html_bundle",
                "version": 3,
                "entry_path": "index.html",
                "files": [
                    {"path": "assets/style.css", "size_bytes": 20},
                    {"path": "index.html", "size_bytes": 120},
                ],
            },
        )
    )
    payload = await call_tool(mcp, "ics_asset_list_files", {"slug_or_id": "abc"})
    assert payload["kind"] == "html_bundle"
    assert payload["entry_path"] == "index.html"
    assert [f["path"] for f in payload["files"]] == ["assets/style.css", "index.html"]
    assert payload["files"][1]["size_bytes"] == 120


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_versions_resolves_id_then_lists(real_client, respx_mock, make_mcp):
    mcp = make_mcp(read)
    mock_resolve(respx_mock)
    respx_mock.get(f"{ICS}/api/assets/{ASSET_ID}/versions").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "version": 1,
                    "size_bytes": 100,
                    "storage_prefix": "x",
                    "created_at": "2026-05-15T08:00:00Z",
                    "created_by": None,
                    "is_current": True,
                }
            ],
        )
    )
    payload = await call_tool(mcp, "ics_asset_versions", {"slug_or_id": "abc"})
    assert payload["versions"][0]["version"] == 1


# ============================================================
#  Write: markdown
# ============================================================


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_md_uploads_and_returns_slug(real_client, respx_mock, make_mcp):
    """Schema-drift regression (response): mock = the real `upload_markdown` shape,
    see the builder in conftest and the contract at CreateMdOut."""
    mcp = make_mcp(write_md)
    respx_mock.post(f"{ICS}/api/assets").mock(
        return_value=httpx.Response(201, json=create_md_response())
    )
    payload = await call_tool(
        mcp,
        "ics_asset_create_md",
        {"payload": {"title": "T", "content": "# Hi"}},
    )
    assert payload["slug"] == "abc"
    assert payload["share_url"] == f"{ICS}/s/tok"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_md_sends_share_mode_in_query_string(real_client, respx_mock, make_mcp):
    """Schema-drift regression (request): `upload_markdown` reads share_mode only
    from the query string; as a form field it is silently ignored
    and every link comes out org_sso."""
    mcp = make_mcp(write_md)
    seen: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        seen["share_mode"] = request.url.params.get("share_mode", "")
        return httpx.Response(201, json=create_md_response())

    respx_mock.post(f"{ICS}/api/assets").mock(side_effect=_capture)
    await call_tool(
        mcp,
        "ics_asset_create_md",
        {"payload": {"title": "T", "content": "x", "share_mode": "public"}, "confirm": True},
    )
    assert seen["share_mode"] == "public"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_md_preserves_dotted_title_without_patch(real_client, respx_mock, make_mcp):
    """The title comes from the filename (backend: `filename.removesuffix('.md')`).
    `Path(...).stem` would turn 'v1.2 release notes' into 'v1'. A faithful
    filename means no follow-up PATCH."""
    mcp = make_mcp(write_md)
    title = "v1.2 release notes"
    seen: dict[str, bytes] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(201, json=create_md_response(title=title))

    respx_mock.post(f"{ICS}/api/assets").mock(side_effect=_capture)
    patch_route = respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "title": title})
    )
    payload = await call_tool(
        mcp, "ics_asset_create_md", {"payload": {"title": title, "content": "x"}}
    )
    assert f'filename="{title}.md"'.encode() in seen["body"]
    assert patch_route.call_count == 0
    assert payload["title"] == title


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_md_attaches_project_via_dedicated_endpoint(real_client, respx_mock, make_mcp):
    """`project_id` does not exist on the create endpoints, so attaching goes
    through a separate PATCH /by-slug/{slug}/project; as a form field it is
    lost and the asset ends up outside the project."""
    mcp = make_mcp(write_md)
    project_id = "00000000-0000-0000-0000-000000000001"
    respx_mock.post(f"{ICS}/api/assets").mock(
        return_value=httpx.Response(201, json=create_md_response())
    )
    attach = respx_mock.patch(f"{ICS}/api/assets/by-slug/abc/project").mock(
        return_value=httpx.Response(200, json={"project_id": project_id})
    )
    await call_tool(
        mcp,
        "ics_asset_create_md",
        {"payload": {"title": "T", "content": "x", "project_id": project_id}},
    )
    assert attach.call_count == 1
    assert json.loads(attach.calls[0].request.content) == {"project_id": project_id}


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_md_followup_failure_surfaces_created_asset(real_client, respx_mock, make_mcp):
    """A failing step after a successful POST must not lose the asset identity;
    otherwise the agent retries create and produces duplicates with active
    share links."""
    mcp = make_mcp(write_md)
    project_id = "00000000-0000-0000-0000-000000000001"
    respx_mock.post(f"{ICS}/api/assets").mock(
        return_value=httpx.Response(201, json=create_md_response())
    )
    respx_mock.patch(f"{ICS}/api/assets/by-slug/abc/project").mock(
        return_value=httpx.Response(403, json={"detail": "you must be a project editor"})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_create_md",
            {"payload": {"title": "T", "content": "x", "project_id": project_id}},
        )
    err = json.loads(str(exc.value))
    assert err["code"] == "forbidden"
    assert err["data"]["slug"] == "abc"
    assert err["data"]["id"] == create_md_response()["id"]
    assert "attaching to the project" in err["message"]  # names the failed step


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_set_tags_resolves_id_and_puts(real_client, respx_mock, make_mcp):
    mcp = make_mcp(write_md)
    mock_resolve(respx_mock)
    respx_mock.put(f"{ICS}/api/assets/{ASSET_ID}/tags").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "tags": ["draft"]})
    )
    payload = await call_tool(mcp, "ics_asset_set_tags", {"slug_or_id": "abc", "tags": ["draft"]})
    assert payload["tags"] == ["draft"]


@pytest.mark.asyncio
async def test_set_tags_rejects_invalid_kebab_locally(real_client, make_mcp):
    """Local Pydantic validation matches ICS `_TAG_RE`, so the agent gets a clear
    error before a useless 422 round-trip."""
    mcp = make_mcp(write_md)
    with pytest.raises(ValidationError) as exc:
        await call_tool(
            mcp,
            "ics_asset_set_tags",
            {"slug_or_id": "abc", "tags": ["Has Spaces"]},
        )
    assert "kebab-case" in str(exc.value)


@pytest.mark.asyncio
async def test_set_tags_normalizes_and_dedupes(real_client, respx_mock, make_mcp):
    """The MCP-side validator normalizes (lower+strip) and deduplicates,
    matching the behaviour of `TagsUpdate` in ICS."""
    mcp = make_mcp(write_md)
    mock_resolve(respx_mock)
    captured: dict[str, list[str]] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["tags"] = json.loads(request.content)["tags"]
        return httpx.Response(200, json={"id": ASSET_ID, "tags": captured["tags"]})

    respx_mock.put(f"{ICS}/api/assets/{ASSET_ID}/tags").mock(side_effect=_capture)
    await call_tool(
        mcp,
        "ics_asset_set_tags",
        {"slug_or_id": "abc", "tags": ["  Draft  ", "draft", "FOO"]},
    )
    assert captured["tags"] == ["draft", "foo"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_delete_dry_run_returns_preview_no_request(real_client, respx_mock, make_mcp):
    """dry_run mode skips the network call entirely."""
    mcp = make_mcp(session_tool, write_md)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    payload = await call_tool(mcp, "ics_asset_delete", {"slug_or_id": "abc"})
    assert payload["action"] == "delete_asset"
    assert payload["target"] == "abc"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_delete_yolo_actually_calls_delete(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, write_md)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    mock_resolve(respx_mock)
    route = respx_mock.delete(f"{ICS}/api/assets/{ASSET_ID}").mock(return_value=httpx.Response(204))
    payload = await call_tool(mcp, "ics_asset_delete", {"slug_or_id": "abc"})
    assert payload["deleted"] is True
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_delete_confirm_true_overrides_interactive_mode(real_client, respx_mock, make_mcp):
    """Per-call `confirm=True` must pass schema validation and
    execute in the default interactive mode: no elicitation, no yolo."""
    mcp = make_mcp(write_md)
    mock_resolve(respx_mock)
    route = respx_mock.delete(f"{ICS}/api/assets/{ASSET_ID}").mock(return_value=httpx.Response(204))
    payload = await call_tool(mcp, "ics_asset_delete", {"slug_or_id": "abc", "confirm": True})
    assert payload["deleted"] is True
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_delete_confirm_false_raises_confirm_required(real_client, respx_mock, make_mcp):
    """Explicit refusal: structured ToolError, no network call."""
    mcp = make_mcp(write_md)
    route = respx_mock.delete(f"{ICS}/api/assets/{ASSET_ID}").mock(return_value=httpx.Response(204))
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_delete", {"slug_or_id": "abc", "confirm": False})
    assert "confirm_required" in str(exc.value)
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_delete_interactive_without_elicitation_hints_confirm(
    real_client, respx_mock, make_mcp
):
    """Client without elicitation capability in interactive mode gets an
    actionable error pointing at the per-call override, not a crash."""
    mcp = make_mcp(write_md)
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_delete", {"slug_or_id": "abc"})
    msg = str(exc.value)
    assert "confirm_required" in msg
    assert "confirm=true" in msg


# ============================================================
#  Write: html
# ============================================================


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_html_posts_json_payload(real_client, respx_mock, make_mcp):
    mcp = make_mcp(write_html)
    respx_mock.post(f"{ICS}/api/assets/html-json").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": ASSET_ID,
                "slug": "abc",
                "title": "T",
                "kind": "html_bundle",
                "entry_path": "index.html",
                "file_count": 1,
                "size_bytes": 10,
                "security_status": "clean",
            },
        )
    )
    payload = await call_tool(
        mcp,
        "ics_asset_create_html",
        {
            "payload": {
                "title": "T",
                "entry_path": "index.html",
                "files": [{"path": "index.html", "content_text": "<html/>"}],
            }
        },
    )
    assert payload["security_status"] == "clean"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_html_security_review_hits_security_endpoint(real_client, respx_mock, make_mcp):
    mcp = make_mcp(write_html)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/security").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "abc",
                "security_status": "warn",
                "security_report": {"findings": []},
                "security_bypass": False,
                "security_bypass_at": None,
                "security_bypass_reason": None,
                "scanned_at": "2026-05-15T08:00:00Z",
            },
        )
    )
    payload = await call_tool(mcp, "ics_asset_html_security_review", {"slug_or_id": "abc"})
    assert payload["security_status"] == "warn"


# ============================================================
#  Share
# ============================================================


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_share_create_link_uses_resolved_id(real_client, respx_mock, make_mcp):
    mcp = make_mcp(share)
    mock_resolve(respx_mock)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/shares").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": ASSET_ID,
                "token": "abc",
                "mode": "org_sso",
                "url": f"{ICS}/s/abc",
                "expires_at": None,
                "max_views": None,
            },
        )
    )
    payload = await call_tool(
        mcp, "ics_share_create_link", {"slug_or_id": "abc", "mode": "org_sso"}
    )
    assert payload["url"].endswith("/s/abc")


# ============================================================
#  Session + help
# ============================================================


@pytest.mark.asyncio
async def test_session_status_returns_current_mode(real_client, make_mcp):
    mcp = make_mcp(session_tool)
    payload = await call_tool(mcp, "ics_session_status", {})
    assert payload["mode"] == "interactive"  # default: same vocabulary as input
    assert payload["protocol_version"] == "2025-11-25"


@pytest.mark.asyncio
async def test_set_mode_echoes_same_vocabulary(real_client, make_mcp):
    """`set_mode` answers with the mode it was given: input and output
    share one mode vocabulary."""
    mcp = make_mcp(session_tool)
    for mode in ("interactive", "yolo", "dry_run"):
        payload = await call_tool(mcp, "ics_session_set_mode", {"mode": mode})
        assert payload["mode"] == mode
        status = await call_tool(mcp, "ics_session_status", {})
        assert status["mode"] == mode


@pytest.mark.asyncio
async def test_ics_help_returns_markdown(real_client, make_mcp):
    mcp = make_mcp(session_tool)
    payload = await call_tool(mcp, "ics_help", {"topic": "overview"})
    assert payload["topic"] == "overview"
    assert "ICS" in payload["content_markdown"]


@pytest.mark.asyncio
async def test_ics_help_tool_selection_topic(real_client, make_mcp):
    """Topic 'tool-selection' is a dedicated decision tree for tool pairs."""
    mcp = make_mcp(session_tool)
    payload = await call_tool(mcp, "ics_help", {"topic": "tool-selection"})
    assert payload["topic"] == "tool-selection"
    md = payload["content_markdown"]
    # Every key pair of overlapping tools must be covered.
    assert "ics_assets_list" in md
    assert "ics_assets_search" in md
    assert "ics_asset_update_content" in md
    assert "ics_asset_new_version" in md
    assert "ics_share_create_link" in md
    assert "ics_share_grant_user" in md
    assert "html_replace_bundle" in md
    assert "content_path" in md


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_whoami_returns_user_info(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool)
    respx_mock.get(f"{ICS}/api/auth/oauth/me").mock(
        return_value=httpx.Response(
            200,
            json={
                "user_id": ASSET_ID,
                "email": "user@example.com",
                "display_name": "U",
                "role": "user",
                "scopes": ["ics"],
                "client_id": "ics-mcp-stdio",
                "transport": "bearer",
                "audience": f"{ICS}/mcp",
            },
        )
    )
    payload = await call_tool(mcp, "ics_whoami", {})
    assert payload["email"] == "user@example.com"


# ============================================================
#  Error mapping in tool surface
# ============================================================


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_404_from_ics_surfaces_as_tool_error(real_client, respx_mock, make_mcp):
    """ICS 404 -> tool raises ToolError with structured payload in message."""
    mcp = make_mcp(discovery)
    respx_mock.get(f"{ICS}/api/assets/by-slug/missing/meta").mock(
        return_value=httpx.Response(404, json={"detail": "no asset"})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_meta", {"slug_or_id": "missing"})
    err = json.loads(str(exc.value))
    assert err["code"] == "not_found"
