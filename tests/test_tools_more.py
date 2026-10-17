"""Extra tool-body coverage: file ops, versions, undelete, pin/unpin,
rename, share grant/revoke."""

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
    write_md,
    write_versions,
)
from ics_mcp.tools import (
    session as session_tool,
)
from tests.conftest import (
    ASSET_ID,
    ICS,
    call_tool,
    create_collection_response,
    mock_resolve,
)

# ----------------- write_md additional -----------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_collection_uploads_files_and_restores_title(
    real_client, respx_mock, make_mcp
):
    """Schema-drift regression (request+response): mock = the real
    `upload_collection` shape (builder in conftest). The backend ignores the
    requested title (derives it from the entry stem), so the tool restores it
    with a follow-up PATCH."""
    mcp = make_mcp(write_md)
    respx_mock.post(f"{ICS}/api/assets/collection").mock(
        return_value=httpx.Response(201, json=create_collection_response(title="a"))
    )
    title_patch = respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "title": "Vault"})
    )
    payload = await call_tool(
        mcp,
        "ics_asset_create_collection",
        {
            "payload": {
                "title": "Vault",
                "files": [
                    {"path": "a.md", "content": "# A"},
                    {"path": "b.md", "content": "# B"},
                ],
            }
        },
    )
    assert title_patch.call_count == 1
    assert json.loads(title_patch.calls[0].request.content) == {"title": "Vault"}
    assert payload["slug"] == "vlt"
    assert payload["title"] == "Vault"
    assert payload["file_count"] == 2
    assert payload["entry_path"] == "a.md"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_collection_sends_share_mode_query_and_attaches_project(
    real_client, respx_mock, make_mcp
):
    """share_mode goes in the query string (as a form field it is lost and the
    link is org_sso), project_id through the dedicated PATCH /by-slug/{slug}/project."""
    mcp = make_mcp(write_md)
    project_id = "00000000-0000-0000-0000-000000000002"
    seen: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        seen["share_mode"] = request.url.params.get("share_mode", "")
        return httpx.Response(201, json=create_collection_response(title="Vault"))

    respx_mock.post(f"{ICS}/api/assets/collection").mock(side_effect=_capture)
    attach = respx_mock.patch(f"{ICS}/api/assets/by-slug/vlt/project").mock(
        return_value=httpx.Response(200, json={"project_id": project_id})
    )
    await call_tool(
        mcp,
        "ics_asset_create_collection",
        {
            "payload": {
                "title": "Vault",
                "files": [{"path": "a.md", "content": "# A"}],
                "share_mode": "public",
                "project_id": project_id,
            },
            "confirm": True,
        },
    )
    assert seen["share_mode"] == "public"
    assert attach.call_count == 1


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_collection_sends_entry_path_and_returns_it(real_client, respx_mock, make_mcp):
    """entry_path goes as a Form field and comes back in the response:
    asserted on the wire (multipart body) and on the payload."""
    mcp = make_mcp(write_md)
    seen: dict[str, bytes] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(201, json=create_collection_response(title="b", entry_path="b.md"))

    respx_mock.post(f"{ICS}/api/assets/collection").mock(side_effect=_capture)
    respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "title": "Vault"})
    )
    payload = await call_tool(
        mcp,
        "ics_asset_create_collection",
        {
            "payload": {
                "title": "Vault",
                "files": [
                    {"path": "a.md", "content": "# A"},
                    {"path": "b.md", "content": "# B"},
                ],
                "entry_path": "b.md",
            }
        },
    )
    assert b'name="entry_path"' in seen["body"]
    assert b"b.md" in seen["body"]
    assert payload["entry_path"] == "b.md"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_collection_entry_path_normalized_like_backend(
    real_client, respx_mock, make_mcp
):
    """The validator and the post-condition compare forms normalized with the
    same algorithm as ICS: './b.md' and 'b.md' are the same path, and the
    backend returns the canonical form of the applied entry."""
    mcp = make_mcp(write_md)
    seen: dict[str, bytes] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        return httpx.Response(201, json=create_collection_response(title="b", entry_path="b.md"))

    respx_mock.post(f"{ICS}/api/assets/collection").mock(side_effect=_capture)
    respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "title": "Vault"})
    )
    payload = await call_tool(
        mcp,
        "ics_asset_create_collection",
        {
            "payload": {
                "title": "Vault",
                "files": [
                    {"path": "a.md", "content": "# A"},
                    {"path": "b.md", "content": "# B"},
                ],
                "entry_path": "./b.md",
            }
        },
    )
    # Canonical form on the wire and no false entry_path_not_applied.
    assert b'name="entry_path"\r\n\r\nb.md' in seen["body"]
    assert payload["entry_path"] == "b.md"


@pytest.mark.asyncio
async def test_create_collection_validates_entry_path_against_files(real_client, make_mcp):
    """An entry_path outside files[].path is an explicit validation error before
    any upload."""
    mcp = make_mcp(write_md)
    with pytest.raises((ToolError, ValidationError)) as exc:
        await call_tool(
            mcp,
            "ics_asset_create_collection",
            {
                "payload": {
                    "title": "Vault",
                    "files": [{"path": "a.md", "content": "# A"}],
                    "entry_path": "ghost.md",
                }
            },
        )
    assert "ghost.md" in str(exc.value)


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_collection_detects_entry_path_ignored_by_old_backend(
    real_client, respx_mock, make_mcp
):
    """Post-condition: a backend without entry_path support would silently
    ignore the Form field, so the tool must detect it from the response
    and return an error carrying the identity of the created asset."""
    mcp = make_mcp(write_md)
    respx_mock.post(f"{ICS}/api/assets/collection").mock(
        # Old backend: pick_entry chose a.md despite b.md being requested.
        return_value=httpx.Response(
            201, json=create_collection_response(title="a", entry_path="a.md")
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_create_collection",
            {
                "payload": {
                    "title": "Vault",
                    "files": [
                        {"path": "a.md", "content": "# A"},
                        {"path": "b.md", "content": "# B"},
                    ],
                    "entry_path": "b.md",
                }
            },
        )
    msg = str(exc.value)
    assert "entry_path_not_applied" in msg
    assert "vlt" in msg  # the slug of the created asset is not lost


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_rename(real_client, respx_mock, make_mcp):
    mcp = make_mcp(write_md)
    mock_resolve(respx_mock)
    respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "title": "New"})
    )
    payload = await call_tool(mcp, "ics_asset_rename", {"slug_or_id": "abc", "title": "New"})
    assert payload["title"] == "New"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_add_file(real_client, respx_mock, make_mcp):
    mcp = make_mcp(write_md)
    mock_resolve(respx_mock)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/files").mock(
        return_value=httpx.Response(200, json={"added_path": "new.md"})
    )
    payload = await call_tool(
        mcp,
        "ics_asset_add_file",
        {"slug_or_id": "abc", "path": "new.md", "content": "x"},
    )
    assert payload["added_path"] == "new.md"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_empty_file(real_client, respx_mock, make_mcp):
    mcp = make_mcp(write_md)
    mock_resolve(respx_mock)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/files/empty").mock(
        return_value=httpx.Response(200, json={"path": "draft.md"})
    )
    payload = await call_tool(
        mcp, "ics_asset_create_empty_file", {"slug_or_id": "abc", "path": "draft.md"}
    )
    assert payload["path"] == "draft.md"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_pin_unpin(real_client, respx_mock, make_mcp):
    mcp = make_mcp(write_md)
    mock_resolve(respx_mock)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/pin").mock(
        return_value=httpx.Response(200, json={"pinned": True})
    )
    respx_mock.delete(f"{ICS}/api/assets/{ASSET_ID}/pin").mock(
        return_value=httpx.Response(200, json={"pinned": False})
    )
    assert (await call_tool(mcp, "ics_asset_pin", {"slug_or_id": "abc"}))["pinned"] is True
    unpinned = await call_tool(mcp, "ics_asset_pin", {"slug_or_id": "abc", "pinned": False})
    assert unpinned["pinned"] is False


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_undelete_with_valid_uuid(real_client, respx_mock, make_mcp):
    mcp = make_mcp(write_md)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/undelete").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "deleted_at": None})
    )
    payload = await call_tool(mcp, "ics_asset_undelete", {"asset_id": ASSET_ID})
    assert payload["id"] == ASSET_ID


@pytest.mark.asyncio
async def test_undelete_with_invalid_uuid_raises(make_mcp):
    mcp = make_mcp(write_md)
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_undelete", {"asset_id": "not-uuid"})
    err = json.loads(str(exc.value))
    assert err["code"] == "id_required"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_update_content_yolo_executes(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, write_md)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    mock_resolve(respx_mock)
    respx_mock.put(f"{ICS}/api/assets/{ASSET_ID}/content").mock(
        return_value=httpx.Response(200, json={"version": 2})
    )
    payload = await call_tool(
        mcp,
        "ics_asset_update_content",
        {"slug_or_id": "abc", "content": "new", "path": "f.md"},
    )
    assert payload["version"] == 2


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_move_file_yolo_executes(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, write_md)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    mock_resolve(respx_mock)
    respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}/files/move").mock(
        return_value=httpx.Response(200, json={"from_path": "a", "to_path": "b"})
    )
    payload = await call_tool(
        mcp,
        "ics_asset_move_file",
        {"slug_or_id": "abc", "from_path": "a", "to_path": "b"},
    )
    assert payload["to_path"] == "b"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_delete_file_yolo_executes(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, write_md)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    mock_resolve(respx_mock)
    respx_mock.delete(f"{ICS}/api/assets/{ASSET_ID}/files").mock(
        return_value=httpx.Response(200, json={"deleted_path": "x.md"})
    )
    payload = await call_tool(mcp, "ics_asset_delete_file", {"slug_or_id": "abc", "path": "x.md"})
    assert payload["deleted_path"] == "x.md"


# ----------------- write_versions -----------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_new_version_uploads(real_client, respx_mock, make_mcp):
    mcp = make_mcp(write_versions)
    mock_resolve(respx_mock)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions").mock(
        return_value=httpx.Response(200, json={"version": 3})
    )
    payload = await call_tool(
        mcp,
        "ics_asset_new_version",
        {
            "slug_or_id": "abc",
            "files": [{"path": "f.md", "content": "x"}],
            "entry_path": "f.md",
            "confirm": True,
        },
    )
    assert payload["version"] == 3


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_restore_version_yolo_executes(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, write_versions)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    mock_resolve(respx_mock)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions/2/restore").mock(
        return_value=httpx.Response(200, json={"version": 4})
    )
    payload = await call_tool(mcp, "ics_asset_restore_version", {"slug_or_id": "abc", "version": 2})
    assert payload["version"] == 4


# ----------------- share additional -----------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_share_grant_user(real_client, respx_mock, make_mcp):
    mcp = make_mcp(share)
    respx_mock.post(f"{ICS}/api/assets/by-slug/abc/shares").mock(
        return_value=httpx.Response(201, json={"email": "u@x", "role": "editor", "id": ASSET_ID})
    )
    payload = await call_tool(
        mcp,
        "ics_share_grant_user",
        {"slug_or_id": "abc", "email": "u@x", "role": "editor"},
    )
    assert payload["email"] == "u@x"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_share_revoke_user_yolo(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, share)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    respx_mock.delete(f"{ICS}/api/assets/by-slug/abc/shares/{ASSET_ID}").mock(
        return_value=httpx.Response(204)
    )
    payload = await call_tool(mcp, "ics_share_revoke", {"slug_or_id": "abc", "user_id": ASSET_ID})
    assert payload["deleted"] is True


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_share_revoke_link_yolo(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, share)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    respx_mock.delete(f"{ICS}/api/shares/{ASSET_ID}").mock(return_value=httpx.Response(204))
    payload = await call_tool(mcp, "ics_share_revoke", {"share_id": ASSET_ID})
    assert payload["deleted"] is True


@pytest.mark.asyncio
@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_share_revoke_needs_exactly_one_target(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, share)
    for args in ({}, {"share_id": ASSET_ID, "user_id": ASSET_ID}, {"slug_or_id": "abc"}):
        with pytest.raises(ToolError) as exc:
            await call_tool(mcp, "ics_share_revoke", {**args, "confirm": True})
        assert "invalid_argument" in str(exc.value)
    # dry_run previews what would be revoked, without a call to ICS.
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    preview = await call_tool(mcp, "ics_share_revoke", {"slug_or_id": "abc", "user_id": ASSET_ID})
    assert preview["target"] == f"access of user {ASSET_ID} to abc"
    assert respx_mock.calls.call_count == 0


# ----------------- discovery additional -----------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_projects_list(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    respx_mock.get(f"{ICS}/api/projects").mock(
        return_value=httpx.Response(200, json=[{"slug": "p1", "name": "P1"}])
    )
    payload = await call_tool(mcp, "ics_projects_list", {})
    assert payload["projects"][0]["slug"] == "p1"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_shares_list_concurrent_fetch(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    mock_resolve(respx_mock)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/shares").mock(
        return_value=httpx.Response(200, json=[{"email": "u@x", "role": "viewer"}])
    )
    respx_mock.get(f"{ICS}/api/assets/{ASSET_ID}/shares").mock(
        return_value=httpx.Response(200, json=[{"token": "t1"}])
    )
    payload = await call_tool(mcp, "ics_shares_list", {"slug_or_id": "abc"})
    assert payload["user_shares"][0]["email"] == "u@x"
    assert payload["share_links"][0]["token"] == "t1"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_outline_with_wait(real_client, respx_mock, make_mcp):
    mcp = make_mcp(discovery)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/outline").mock(
        return_value=httpx.Response(200, json={"kind": "md_single", "headings": []})
    )
    payload = await call_tool(mcp, "ics_asset_outline", {"slug_or_id": "abc", "wait": True})
    assert payload["kind"] == "md_single"


# ----------------- read additional -----------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_read_rendered(real_client, respx_mock, make_mcp):
    mcp = make_mcp(read)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/doc").mock(
        return_value=httpx.Response(200, json={"html": "<h1>Hi</h1>"})
    )
    payload = await call_tool(mcp, "ics_asset_read_rendered", {"slug_or_id": "abc"})
    assert payload["content"] == "<h1>Hi</h1>"
    assert "html" not in payload


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_diff(real_client, respx_mock, make_mcp):
    mcp = make_mcp(read)
    mock_resolve(respx_mock)
    respx_mock.get(f"{ICS}/api/assets/{ASSET_ID}/versions/1/diff/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "kind": "md_single",
                "from_version": 1,
                "to_version": 2,
                "diff": "@@...",
            },
        )
    )
    payload = await call_tool(mcp, "ics_asset_diff", {"slug_or_id": "abc", "v1": 1, "v2": 2})
    assert "@@" in payload["diff"]


# ============================================================
#  Read-only access to archived versions
# ============================================================


# Three tools, one rule: `version` goes to the query and comes back in the payload.
_VERSION_PASSTHROUGH = [
    (
        "ics_asset_read",
        "file-mcp",
        {
            "slug": "abc",
            "path": "old/start.md",
            "content": "old content",
            "total_lines": 1,
            "returned_range": [1, 1],
            "version": 1,
            "current_version": 3,
        },
    ),
    (
        "ics_asset_list_files",
        "files-mcp",
        {
            "slug": "abc",
            "kind": "md_collection",
            "version": 1,
            "current_version": 3,
            "entry_path": "old/start.md",
            "files": [{"path": "old/start.md", "size_bytes": 12}],
        },
    ),
    (
        "ics_asset_read_rendered",
        "doc",
        {
            "slug": "abc",
            "html": "<p>v1</p>",
            "version": 1,
            "preview_version": 1,
            "current_version": 3,
        },
    ),
]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_version_arg_reaches_backend_and_returns(real_client, respx_mock, make_mcp):
    """The agent must get `version` and `current_version` back; otherwise it
    cannot tell whether it reads an archived version without an extra
    round-trip.

    A loop, not `parametrize`: the `respx.mock` decorator hides the test
    signature, so pytest would take the parameters for fixtures."""
    mcp = make_mcp(read, discovery)
    for tool, endpoint, stub in _VERSION_PASSTHROUGH:
        route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/{endpoint}").mock(
            return_value=httpx.Response(200, json=stub)
        )
        payload = await call_tool(mcp, tool, {"slug_or_id": "abc", "version": 1})
        assert route.calls[0].request.url.params["version"] == "1", tool
        assert (payload["version"], payload["current_version"]) == (1, 3), tool


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_read_omits_version_param_by_default(real_client, respx_mock, make_mcp):
    """Without `version` the request carries no `version` query parameter."""
    mcp = make_mcp(read)
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "abc",
                "path": "index.md",
                "content": "x",
                "total_lines": 1,
                "returned_range": [1, 1],
                "version": 3,
                "current_version": 3,
            },
        )
    )
    await call_tool(mcp, "ics_asset_read", {"slug_or_id": "abc"})
    assert "version" not in route.calls[0].request.url.params


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_versions_tolerates_masked_fields(real_client, respx_mock, make_mcp):
    """A read-only collaborator gets `storage_prefix: null` and an empty
    `author_email`, and the model must not choke on that."""
    mcp = make_mcp(read)
    mock_resolve(respx_mock)
    respx_mock.get(f"{ICS}/api/assets/{ASSET_ID}/versions").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "version": 2,
                    "size_bytes": 10,
                    "storage_prefix": None,
                    "created_at": "2026-03-01T09:00:00Z",
                    "created_by": None,
                    "author": "test.author",
                    "author_email": None,
                    "is_current": True,
                }
            ],
        )
    )
    payload = await call_tool(mcp, "ics_asset_versions", {"slug_or_id": "abc"})
    row = payload["versions"][0]
    assert row["author"] == "test.author"
    assert row["storage_prefix"] is None
    assert "@" not in row["author"]
