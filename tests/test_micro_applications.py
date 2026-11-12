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
        "app_url_pattern": "https://a-<hex>-prod.apps.example/",
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
        "title": "App",
        "desired_state": "enabled",
        "runtime": {"state": "sleeping", "x": "y" * 500},
        "active_release": {"id": "r1"},
        "package_version": 2,
        "generation": 4,
        "app_url": "https://a/",
        "rights": {},
    }
    respx_mock.get(BASE).mock(return_value=httpx.Response(200, json={"items": [item], "total": 1}))
    out = await call_tool(make_mcp(micro_applications), "ics_microapp_status", {})
    assert out["items"] == [
        {
            "asset_id": ASSET_ID,
            "title": "App",
            "desired_state": "enabled",
            "runtime": "sleeping",
            "release": "r1",
            "package_version": 2,
            "generation": 4,
            "app_url": "https://a/",
        }
    ]


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
