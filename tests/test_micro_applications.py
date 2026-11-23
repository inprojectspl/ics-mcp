"""Micro-application tools: thin adapters over the ICS management API.

Mocks follow `/api/micro-applications/*` of ICS (PoC contract
`ics.microapp/v1alpha1`)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp.config import get_settings
from ics_mcp.tools import discovery, micro_applications, read
from tests.conftest import ASSET_ID, ICS, asset_meta, call_tool

BASE = f"{ICS}/api/micro-applications"


def contract(schema_chars: int = 30_000) -> dict[str, Any]:
    return {
        "contract_version": "ics.microapp/v1alpha1",
        "profile": "js-capabilities-v1",
        "sdk_version": "1.0",
        "contract_hash": "sha256:abc",
        "app_url_pattern": "https://<8-character app name>.apps.example/",
        "sections": {
            "manifest_schema": {"description": "x" * schema_chars},
            "procedure": ["plan", "apply"],
            "limits": {"max_files": 50},
        },
    }


def op(**over: Any) -> dict[str, Any]:
    base = {
        "operation_id": "op_1",
        "status": "pending",
        "terminal": False,
        "step": "accepted",
        "replayed": False,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_contract_overview_and_parts_share_one_hash_under_the_cap(
    real_client, respx_mock, make_mcp
):
    respx_mock.get(f"{BASE}/contract").mock(return_value=httpx.Response(200, json=contract()))
    mcp = make_mcp(micro_applications)
    overview = await call_tool(mcp, "ics_microapp_contract", {})
    assert overview["contract_hash"] == "sha256:abc"
    assert overview["sections"]["manifest_schema"]["chars"] > 30_000
    first = await call_tool(mcp, "ics_microapp_contract", {"section": "manifest_schema"})
    assert first["parts"] > 1 and first["contract_hash"] == "sha256:abc"
    chunks = [first["content_json"]]
    for part in range(2, first["parts"] + 1):
        out = await call_tool(
            mcp, "ics_microapp_contract", {"section": "manifest_schema", "part": part}
        )
        assert len(json.dumps(out)) <= get_settings().mcp_response_max_chars
        chunks.append(out["content_json"])
    assert json.loads("".join(chunks)) == contract()["sections"]["manifest_schema"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_plan_sends_the_complete_package(real_client, respx_mock, make_mcp, tmp_path):
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "index.html").write_text("<p>x</p>")
    (tmp_path / "microapp.json").write_text("{}")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ignored")
    route = respx_mock.post(f"{BASE}/plans").mock(
        return_value=httpx.Response(
            201, json={"plan_id": "plan_1", "release_digest": "sha256:d", "expected_generation": 0}
        )
    )
    out = await call_tool(
        make_mcp(micro_applications), "ics_microapp_plan", {"package_dir": str(tmp_path)}
    )
    sent = json.loads(route.calls[0].request.content)
    assert sorted(f["path"] for f in sent["files"]) == ["microapp.json", "public/index.html"]
    assert out["plan_id"] == "plan_1" and "ics_microapp_apply" in out["next"]


@pytest.mark.asyncio
async def test_plan_refuses_local_paths_over_http(real_client, make_mcp, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "mcp_transport", "http")
    with pytest.raises(ToolError) as exc:
        await call_tool(
            make_mcp(micro_applications), "ics_microapp_plan", {"package_dir": str(tmp_path)}
        )
    assert "only available over stdio" in str(exc.value)


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_apply_uses_a_stable_key_so_a_retry_is_the_same_operation(
    real_client, respx_mock, make_mcp
):
    route = respx_mock.post(f"{BASE}/plans/plan_abc/apply").mock(
        side_effect=[httpx.Response(202, json=op()), httpx.Response(200, json=op(replayed=True))]
    )
    args = {"plan_id": "plan_abc", "digest": "sha256:d", "expected_generation": 0, "confirm": True}
    mcp = make_mcp(micro_applications)
    a = await call_tool(mcp, "ics_microapp_apply", args)
    b = await call_tool(mcp, "ics_microapp_apply", args)
    keys = [json.loads(c.request.content)["idempotency_key"] for c in route.calls]
    assert keys[0] == keys[1] == "apply-plan_abc"
    assert a["operation_id"] == b["operation_id"] and b["replayed"] is True


@pytest.mark.asyncio
@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_apply_asks_for_confirmation_in_interactive_mode(real_client, respx_mock, make_mcp):
    with pytest.raises(ToolError) as exc:
        await call_tool(
            make_mcp(micro_applications),
            "ics_microapp_apply",
            {"plan_id": "plan_abc", "digest": "sha256:d", "expected_generation": 0},
        )
    assert "confirm_required" in str(exc.value)
    assert respx_mock.calls.call_count == 0


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_apply_conflict_keeps_the_ics_code(real_client, respx_mock, make_mcp):
    respx_mock.post(f"{BASE}/plans/plan_abc/apply").mock(
        return_value=httpx.Response(
            409, json={"code": "idempotency_key_reused", "detail": "different request"}
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            make_mcp(micro_applications),
            "ics_microapp_apply",
            {
                "plan_id": "plan_abc",
                "digest": "sha256:x",
                "expected_generation": 0,
                "confirm": True,
            },
        )
    assert "idempotency_key_reused" in str(exc.value)


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_status_list_is_compact(real_client, respx_mock, make_mcp):
    item = {
        "asset_id": ASSET_ID,
        "slug": "app1",
        "title": "App",
        "desired_state": "enabled",
        "runtime": {"state": "running", "x": "y" * 500, "realtime": {"sockets": 5, "people": 3}},
        "active_release": {"id": "r1"},
        "package_version": 2,
        "generation": 4,
        "app_url": "https://k7m2q9x4.apps.example/",
        "rights": {},
    }
    respx_mock.get(BASE).mock(return_value=httpx.Response(200, json={"items": [item], "total": 1}))
    out = await call_tool(make_mcp(micro_applications), "ics_microapp_status", {})
    assert out["items"] == [
        {
            "asset_id": ASSET_ID,
            "slug": "app1",
            "title": "App",
            "desired_state": "enabled",
            "runtime": "running",
            "live_people": 3,
            "release": "r1",
            "package_version": 2,
            "generation": 4,
            "app_url": "https://k7m2q9x4.apps.example/",
        }
    ]


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_status_of_one_app_keeps_the_live_counts(real_client, respx_mock, make_mcp):
    runtime = {"state": "running", "fresh": True, "realtime": {"sockets": 5, "people": 3}}
    respx_mock.get(f"{BASE}/{ASSET_ID}").mock(
        return_value=httpx.Response(200, json={"asset_id": ASSET_ID, "runtime": runtime})
    )
    out = await call_tool(
        make_mcp(micro_applications), "ics_microapp_status", {"asset_id": ASSET_ID}
    )
    assert out["runtime"]["realtime"] == {"sockets": 5, "people": 3}


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_control_sends_action_generation_and_a_derived_key(real_client, respx_mock, make_mcp):
    route = respx_mock.post(f"{BASE}/{ASSET_ID}/control").mock(
        return_value=httpx.Response(200, json=op(status="succeeded"))
    )
    await call_tool(
        make_mcp(micro_applications),
        "ics_microapp_control",
        {"asset_id": ASSET_ID, "action": "suspend", "expected_generation": 7, "confirm": True},
    )
    body = json.loads(route.calls[0].request.content)
    assert body["action"] == "suspend" and body["expected_generation"] == 7
    assert body["idempotency_key"] == f"control-{ASSET_ID[:8]}-suspend-g7"


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_read_of_a_micro_application_uses_the_author_route(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/app/file-mcp").mock(
        return_value=httpx.Response(
            403, json={"code": "microapp_source_restricted", "detail": "no"}
        )
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/app/meta").mock(
        return_value=httpx.Response(200, json=asset_meta(slug="app", kind="micro_application"))
    )
    respx_mock.get(f"{BASE}/{ASSET_ID}/package").mock(
        return_value=httpx.Response(
            200,
            json={
                "path": "handlers/a.mjs",
                "version": 1,
                "content": "export default 1",
                "encoding": "utf-8",
            },
        )
    )
    out = await call_tool(
        make_mcp(read), "ics_asset_read", {"slug_or_id": "app", "path": "handlers/a.mjs"}
    )
    assert out["content"] == "export default 1" and out["path"] == "handlers/a.mjs"


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_list_files_of_a_micro_application_needs_publish_rights(
    real_client, respx_mock, make_mcp
):
    respx_mock.get(f"{ICS}/api/assets/by-slug/app/files-mcp").mock(
        return_value=httpx.Response(
            403, json={"code": "microapp_source_restricted", "detail": "no"}
        )
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/app/meta").mock(
        return_value=httpx.Response(200, json=asset_meta(slug="app", kind="micro_application"))
    )
    respx_mock.get(f"{BASE}/{ASSET_ID}/package").mock(
        return_value=httpx.Response(
            403, json={"code": "publish_permission_required", "detail": "publishers only"}
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(make_mcp(discovery), "ics_asset_list_files", {"slug_or_id": "app"})
    assert "publish_permission_required" in str(exc.value)


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_share_link_of_a_micro_application_carries_app_permissions(
    real_client, respx_mock, make_mcp
):
    from ics_mcp.tools import share
    from tests.conftest import mock_resolve

    mock_resolve(respx_mock)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/shares").mock(
        return_value=httpx.Response(
            201,
            json={"id": "s1", "token": "t", "mode": "org_sso", "app_permissions": ["game.play"]},
        )
    )
    await call_tool(
        make_mcp(share),
        "ics_share_create_link",
        {"slug_or_id": "abc", "mode": "org_sso", "app_permissions": ["game.play"]},
    )
    assert json.loads(route.calls[0].request.content)["app_permissions"] == ["game.play"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_access_set_sends_exact_permissions_and_opens_for_a_person(
    real_client, respx_mock, make_mcp
):
    from ics_mcp.tools import micro_app_access

    put = respx_mock.put(f"{BASE}/{ASSET_ID}/access").mock(
        return_value=httpx.Response(
            200,
            json={"added": ["requests.read"], "removed": [], "open_change": "viewer_share_added"},
        )
    )
    respx_mock.get(f"{BASE}/{ASSET_ID}/access").mock(
        return_value=httpx.Response(200, json={"permissions": [], "people": [], "projects": []})
    )
    mcp = make_mcp(micro_app_access)
    out = await call_tool(
        mcp,
        "ics_microapp_access_set",
        {
            "asset_id": ASSET_ID,
            "user_email": "bob@example.com",
            "permissions": ["requests.read", "requests.read"],
            "confirm": True,
        },
    )
    assert out["open_change"] == "viewer_share_added"
    sent = json.loads(put.calls.last.request.content)
    # Duplicates collapse; a person with permissions may open the app.
    assert sent == {
        "roles": [],
        "permissions": ["requests.read"],
        "can_open": True,
        "user_email": "bob@example.com",
    }
    view = await call_tool(mcp, "ics_microapp_access", {"asset_id": ASSET_ID})
    assert view["people"] == []


def test_access_confirmation_names_the_viewer_share_it_adds():
    from ics_mcp.tools.micro_app_access import _describe

    text = _describe(asset_id="a1", user_email="bob@x", permissions=["r.read"], can_open=None)
    assert "may open the app" in text and "exactly r.read" in text
    text = _describe(asset_id="a1", user_email="bob@x", roles=["reviewer"], can_open=None)
    assert "exactly role reviewer; may open the app" in text
    text = _describe(asset_id="a1", project_id="p1")
    assert text == "project p1 in a1: exactly nothing"


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_access_set_gives_a_role_and_a_link_carries_roles(real_client, respx_mock, make_mcp):
    from ics_mcp.tools import micro_app_access, share
    from tests.conftest import mock_resolve

    put = respx_mock.put(f"{BASE}/{ASSET_ID}/access").mock(
        return_value=httpx.Response(200, json={"roles_added": ["reviewer"], "open_change": None})
    )
    await call_tool(
        make_mcp(micro_app_access),
        "ics_microapp_access_set",
        {"asset_id": ASSET_ID, "project_id": "p1", "roles": ["reviewer"], "confirm": True},
    )
    # A project is not "opened" by this call: only a person gets a viewer share.
    assert json.loads(put.calls.last.request.content) == {
        "roles": ["reviewer"],
        "permissions": [],
        "can_open": None,
        "project_id": "p1",
    }

    mock_resolve(respx_mock)
    link = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/shares").mock(
        return_value=httpx.Response(201, json={"id": "s1", "app_roles": ["reviewer"]})
    )
    await call_tool(
        make_mcp(share),
        "ics_share_create_link",
        {"slug_or_id": "abc", "mode": "org_sso", "app_roles": ["reviewer"]},
    )
    assert json.loads(link.calls[0].request.content) == {
        "mode": "org_sso",
        "app_roles": ["reviewer"],
    }


@pytest.mark.asyncio
async def test_access_set_needs_exactly_one_principal(real_client, make_mcp):
    from ics_mcp.tools import micro_app_access

    mcp = make_mcp(micro_app_access)
    with pytest.raises(ToolError, match="exactly one of user_email or project_id"):
        await call_tool(
            mcp,
            "ics_microapp_access_set",
            {"asset_id": ASSET_ID, "permissions": [], "confirm": True},
        )


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_reading_an_app_returns_its_document_and_pages_by_collection(
    real_client, respx_mock, make_mcp
):
    respx_mock.get(f"{ICS}/api/assets/by-slug/app1/file-mcp").mock(
        return_value=httpx.Response(403, json={"code": "microapp_source_restricted", "detail": "x"})
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/app1/meta").mock(
        return_value=httpx.Response(200, json=asset_meta(slug="app1", kind="micro_application"))
    )
    doc = respx_mock.get(f"{BASE}/{ASSET_ID}/document").mock(
        return_value=httpx.Response(
            200,
            json={
                "markdown": "# App\n\n## App view\n",
                "html": "<h1>App</h1>",
                "collections": [{"name": "requests", "readable": True, "next_cursor": "c2"}],
                "app_view": {"endpoint": "document", "error": None},
            },
        )
    )
    mcp = make_mcp(read)
    out = await call_tool(mcp, "ics_asset_read", {"slug_or_id": "app1"})
    assert out["content"] == "# App\n\n## App view\n" and out["next_cursors"] == {"requests": "c2"}
    assert out["app_view"] == {"endpoint": "document", "error": None}
    assert out["path"] == "app.md" and out["format"] == "markdown"
    await call_tool(
        mcp, "ics_asset_read", {"slug_or_id": "app1", "path": "data/requests", "cursor": "c2"}
    )
    assert doc.calls.last.request.url.params["collection"] == "requests"
    assert doc.calls.last.request.url.params["cursor"] == "c2"
    # ICS slices the document like a file read; the agent never gets HTML.
    doc.mock(
        return_value=httpx.Response(
            200, json={"markdown": "# App", "total_lines": 4, "returned_range": [1, 2]}
        )
    )
    head = await call_tool(mcp, "ics_asset_read", {"slug_or_id": "app1", "max_lines": 2})
    sent = doc.calls.last.request.url.params
    assert sent["lines"] == "1-2" and sent["max_lines"] == "2" and sent["html"] == "false"
    assert head["truncated"] is True and head["returned_range"] == [1, 2]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_generic_tools_point_an_agent_at_the_app_read(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/app1/outline").mock(
        return_value=httpx.Response(403, json={"code": "microapp_source_restricted", "detail": "x"})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(make_mcp(discovery), "ics_asset_outline", {"slug_or_id": "app1"})
    assert "ics_asset_read(slug_or_id)" in str(exc.value)

    respx_mock.get(f"{ICS}/api/assets/by-slug/app1/file-mcp").mock(
        return_value=httpx.Response(403, json={"code": "microapp_source_restricted", "detail": "x"})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(make_mcp(read), "ics_asset_read", {"slug_or_id": "app1", "version": 2})
    # An archived app has only its package: no silent read of the current one.
    assert "invalid_argument" in str(exc.value) and "path=" in str(exc.value)


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_a_long_app_comparison_keeps_what_changed_in_the_app(
    real_client, respx_mock, make_mcp, monkeypatch
):
    monkeypatch.setattr(get_settings(), "mcp_response_max_chars", 1500)
    respx_mock.get(f"{ICS}/api/assets/by-slug/app1/meta").mock(
        return_value=httpx.Response(200, json=asset_meta(slug="app1", kind="micro_application"))
    )
    files = [{"path": f"public/f{i}.js", "change": "modified"} for i in range(200)]
    change = {"area": "role", "name": "reviewer", "change": "changed", "detail": "+x"}
    respx_mock.get(f"{ICS}/api/assets/{ASSET_ID}/versions/1/diff/2").mock(
        return_value=httpx.Response(200, json={"files": files, "app_changes": [change]})
    )
    out = await call_tool(
        make_mcp(read), "ics_asset_diff", {"slug_or_id": "app1", "v1": 1, "v2": 2}
    )
    assert out["app_changes"] == [change] and out["truncated"] is True and out["omitted"] > 0


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_a_plan_carries_the_release_note(real_client, respx_mock, make_mcp):
    route = respx_mock.post(f"{BASE}/plans").mock(
        return_value=httpx.Response(201, json={"plan_id": "plan_x", "app_changes": []})
    )
    files = [{"path": "microapp.json", "content_text": "{}"}]
    await call_tool(
        make_mcp(micro_applications),
        "ics_microapp_plan",
        {"files": files, "change_note": "Reviewers export"},
    )
    assert json.loads(route.calls.last.request.content)["change_note"] == "Reviewers export"
