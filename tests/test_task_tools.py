"""Task tools (ICS ADR-0018, ADR-0019). Response mocks follow the ICS contract
(`services/context_pack_output.py`, `services/external_refs.py`,
`services/project_links.py`)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from ics_mcp._payload import payload_chars
from ics_mcp.config import get_settings
from ics_mcp.tools import session as session_tool
from ics_mcp.tools import tasks
from tests.conftest import ASSET_ID, ICS, call_tool, mock_resolve

REF_ID = "66666666-6666-6666-6666-666666666666"
KEY_ID = "77777777-7777-7777-7777-777777777777"


def ics_error(status: int, code: str, **extra: Any) -> httpx.Response:
    return httpx.Response(status, json={"detail": code.replace("_", " "), "code": code, **extra})


def error_payload(exc: pytest.ExceptionInfo[ToolError]) -> dict[str, Any]:
    return json.loads(str(exc.value))


def doc(i: int, *, required: bool = False, summary_len: int = 200) -> dict[str, Any]:
    slug = f"doc{i:04d}"
    return {
        "ref": f"ics://asset/{slug}",
        "slug": slug,
        "title": f"Document {i}",
        "summary": "x" * summary_len,
        "doc_type": "specification",
        "doc_type_hint": None,
        "kind": "md_single",
        "version": 1,
        "content_updated_at": "2026-09-20T08:12:00+00:00",
        "freshness": "current",
        "flags": [],
        "required": required,
        "via": [{"kind": "direct", "role": "context", "required": required}],
        "estimated_tokens": 900,
        "has_outline": True,
    }


def pack(documents: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "project": {"slug": "sffyr92muy", "name": "Acme", "external": "acme-app"},
        "task": {"system": "openproject", "wp": "4711", "ancestors": ["4700"]},
        "documents": documents,
        "edges": [],
        "warnings": [],
        "truncated": None,
    }
    body.update(overrides)
    # ICS reports the size of the whole response (4 characters per token).
    body["estimated_tokens"] = 0
    body["estimated_tokens"] = -(-payload_chars(body) // 4) + 2
    return body


def mock_meta(respx_mock, asset_id: str = ASSET_ID) -> None:
    """The meta a UUID argument resolves to; the results name the document by it."""
    respx_mock.get(f"{ICS}/api/assets/{asset_id}").mock(
        return_value=httpx.Response(200, json={"id": asset_id, "slug": "spec", "title": "Spec"})
    )


def ext_ref(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": REF_ID,
        "asset_id": ASSET_ID,
        "system": "openproject",
        "entity": "work_package",
        "external_id": "4711",
        "external_scope": "acme-app",
        "role": "context",
        "required": True,
        "label": "Book a tool with conflict check",
        "url": None,
        "asset_path": None,
        "pinned_version": 2,
        "basis_changed": False,
        "note": None,
        "origin": "agent",
        "created_at": "2026-09-26T10:00:00+00:00",
    }
    base.update(overrides)
    return base


# ------------------------------- ics_task_context -------------------------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_context_passes_params(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    route = respx_mock.get(f"{ICS}/api/context").mock(
        return_value=httpx.Response(200, json=pack([doc(1, required=True), doc(2)]))
    )
    payload = await call_tool(
        mcp,
        "ics_task_context",
        {
            "wp": "4711",
            "ancestors": ["4700", "4650"],
            "project": "acme-app",
            "depth": 2,
            "budget_tokens": 2500,
            "include": ["deliverables", "references"],
        },
    )
    params = route.calls[0].request.url.params
    assert params["wp"] == "4711"
    assert params["system"] == "openproject"
    assert params.get_list("ancestors") == ["4700", "4650"]
    assert params["project"] == "acme-app"
    assert params["depth"] == "2"
    assert params["budget_tokens"] == "2500"
    assert params.get_list("include") == ["deliverables", "references"]
    assert "scope" not in params
    assert [d["slug"] for d in payload["documents"]] == ["doc0001", "doc0002"]
    assert "hint" not in payload


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_context_ps_node_uses_project_as_scope(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    route = respx_mock.get(f"{ICS}/api/context").mock(
        return_value=httpx.Response(200, json=pack([doc(1)]))
    )
    await call_tool(
        mcp,
        "ics_task_context",
        {"wp": "n-8f2c", "system": "project_standard", "project": "ps-local"},
    )
    params = route.calls[0].request.url.params
    assert params["system"] == "project_standard"
    assert params["scope"] == "ps-local"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_context_empty_pack_has_hint(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    respx_mock.get(f"{ICS}/api/context").mock(
        return_value=httpx.Response(200, json=pack([], project=None))
    )
    payload = await call_tool(mcp, "ics_task_context", {"wp": "9999"})
    assert payload["documents"] == []
    assert payload["project"] is None
    assert "ics_task_link" in payload["hint"]
    assert "truncated" not in payload or payload["truncated"] is None


@pytest.mark.parametrize(
    ("cut", "expected"),
    [
        ({"needed_tokens": 2600, "seed": None}, "`budget_tokens=2600`"),
        ({"needed_tokens": 5200, "seed": "doc0001"}, "slug_or_id='doc0001'"),
        ({"needed_tokens": 5200, "seed": None}, "drop `include`"),
    ],
)
@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_context_truncation_hint_comes_from_the_numbers(
    real_client, respx_mock, make_mcp, cut, expected
):
    mcp = make_mcp(tasks)
    truncated = {"documents": 3, "neighbours": 2, "max_budget_tokens": 4000, **cut}
    body = pack([doc(1)], truncated=truncated)
    respx_mock.get(f"{ICS}/api/context").mock(return_value=httpx.Response(200, json=body))
    payload = await call_tool(mcp, "ics_task_context", {"wp": "4711"})
    assert payload["truncated"] == {**truncated, "hint": payload["truncated"]["hint"]}
    assert expected in payload["truncated"]["hint"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_context_warnings_keep_data_and_gain_a_message(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    warnings = [
        {"code": "superseded", "params": {"slug": "old", "successor": "new", "required": True}},
        {"code": "basis_changed", "params": {"slug": "doc0001"}},
        {"code": "contradicts", "params": {"from": "a", "to": "b"}},
        {"code": "project_unmapped", "params": {"project": "acme"}},
        {"code": "task_unlinked", "params": {"system": "openproject", "wp": "4711"}},
        {"code": "future_code", "params": {"x": 1}},
    ]
    body = pack([doc(1)], warnings=warnings)
    respx_mock.get(f"{ICS}/api/context").mock(return_value=httpx.Response(200, json=body))
    payload = await call_tool(mcp, "ics_task_context", {"wp": "4711", "project": "acme"})
    got = payload["warnings"]
    assert [{"code": w["code"], "params": w["params"]} for w in got] == warnings
    assert got[0]["message"] == "Required document old is superseded; use new."
    assert "doc0001" in got[1]["message"]
    assert got[2]["message"] == "Documents a and b contradict each other."
    assert "ics_project_links" in got[3]["message"]
    assert "4711" in got[4]["message"] and "ics_task_link" in got[4]["message"]
    assert got[5]["message"].startswith("future_code")


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_context_without_project_warns_that_key_documents_were_skipped(
    real_client, respx_mock, make_mcp
):
    mcp = make_mcp(tasks)
    respx_mock.get(f"{ICS}/api/context").mock(
        return_value=httpx.Response(200, json=pack([doc(1)], project=None))
    )
    payload = await call_tool(mcp, "ics_task_context", {"wp": "4711"})
    warning = payload["warnings"][-1]
    assert warning["code"] == "project_missing"
    assert "ics_projects_list" in warning["message"]
    with_project = await call_tool(mcp, "ics_task_context", {"wp": "4711", "project": "acme"})
    assert all(w["code"] != "project_missing" for w in with_project["warnings"])


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_context_budget_4000_not_cut_by_general_limit(real_client, respx_mock, make_mcp):
    """A 4000-token pack may take up to 16000 characters, past the
    general 8000-character limit of the other tools: the cap follows the
    pack's own size, nothing is cut again."""
    assert get_settings().mcp_response_max_chars == 8000
    mcp = make_mcp(tasks)
    documents = [doc(i, summary_len=400) for i in range(1, 16)]
    body = pack(documents)
    assert 8000 < payload_chars(body) <= 16000
    respx_mock.get(f"{ICS}/api/context").mock(return_value=httpx.Response(200, json=body))
    payload = await call_tool(mcp, "ics_task_context", {"wp": "4711", "budget_tokens": 4000})
    assert payload["documents"] == documents
    assert payload["truncated"] is None
    assert payload_chars(payload) > 8000


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_context_passes_the_pack_through(real_client, respx_mock, make_mcp):
    """ICS fits the pack to the budget; a required document over it stays and
    the tool does not cut anything itself."""
    mcp = make_mcp(tasks)
    documents = [doc(1, required=True, summary_len=12000), doc(2)]
    edges = [{"from": "doc0001", "to": "doc0002", "type": "derived_from"}]
    body = pack(documents, edges=edges)
    route = respx_mock.get(f"{ICS}/api/context").mock(return_value=httpx.Response(200, json=body))
    payload = await call_tool(mcp, "ics_task_context", {"wp": "4711"})
    assert route.calls[0].request.url.params["budget_tokens"] == str(tasks.DEFAULT_BUDGET)
    assert payload["documents"] == documents
    assert payload["edges"] == edges


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_context_larger_than_ics_claims_is_stubbed(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    body = pack([doc(i, summary_len=400) for i in range(1, 40)])
    body["estimated_tokens"] = 500
    respx_mock.get(f"{ICS}/api/context").mock(return_value=httpx.Response(200, json=body))
    payload = await call_tool(mcp, "ics_task_context", {"wp": "4711"})
    assert payload["truncated"] is True
    assert payload["cap_chars"] == 8000
    assert "budget_tokens" in payload["hint"]


@pytest.mark.asyncio
async def test_context_budget_is_capped(real_client, make_mcp):
    mcp = make_mcp(tasks)
    with pytest.raises(ValidationError):
        await call_tool(mcp, "ics_task_context", {"wp": "4711", "budget_tokens": 4001})


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_context_invalid_key_is_promoted(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    respx_mock.get(f"{ICS}/api/context").mock(
        return_value=ics_error(400, "external_ref_invalid", field="external_id")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_task_context", {"wp": "not-a-number"})
    err = error_payload(exc)
    assert err["code"] == "external_ref_invalid"
    assert err["field"] == "external_id"
    assert "work package" in err["hint"]


# -------------------------------- ics_task_link --------------------------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_task_link_work_package(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    mock_resolve(respx_mock)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/external-refs").mock(
        return_value=httpx.Response(201, json=ext_ref())
    )
    payload = await call_tool(
        mcp,
        "ics_task_link",
        {
            "slug_or_id": "abc",
            "wp": "4711",
            "role": "context",
            "project": "acme-app",
            "required": True,
            "label": "Book a tool with conflict check",
        },
    )
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "system": "openproject",
        "entity": "work_package",
        "external_id": "4711",
        "external_scope": "acme-app",
        "role": "context",
        "required": True,
        "label": "Book a tool with conflict check",
    }
    # Compact: no asset UUID, no entity/url/origin/created_at, no nulls or defaults.
    assert payload == {
        "asset": {"slug": "abc"},
        "id": REF_ID,
        "wp": "4711",
        "project": "acme-app",
        "role": "context",
        "required": True,
        "label": "Book a tool with conflict check",
        "pinned_version": 2,
    }


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_task_link_ps_node(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    mock_meta(respx_mock)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/external-refs").mock(
        return_value=httpx.Response(
            201, json=ext_ref(system="project_standard", entity="node", external_id="n-8f2c")
        )
    )
    payload = await call_tool(
        mcp,
        "ics_task_link",
        {
            "slug_or_id": ASSET_ID,
            "wp": "n-8f2c",
            "system": "project_standard",
            "project": "ps-local",
            "role": "deliverable",
            "path": "notes/report.md",
            "pinned_version": 3,
            "note": "Produced by the task.",
        },
    )
    body = json.loads(route.calls[0].request.content)
    assert body["system"] == "project_standard"
    assert body["entity"] == "node"
    assert body["external_scope"] == "ps-local"
    assert body["asset_path"] == "notes/report.md"
    assert body["pinned_version"] == 3
    assert body["role"] == "deliverable"
    assert body["required"] is False
    assert payload["asset"] == {"slug": "spec", "title": "Spec"}
    assert payload["system"] == "project_standard"
    assert payload["wp"] == "n-8f2c"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_task_link_ps_node_needs_project(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/external-refs")
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_task_link",
            {
                "slug_or_id": ASSET_ID,
                "wp": "n-8f2c",
                "system": "project_standard",
                "role": "context",
            },
        )
    err = error_payload(exc)
    assert err["code"] == "external_ref_invalid"
    assert err["field"] == "project"
    assert not route.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_task_link_exists(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    mock_meta(respx_mock)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/external-refs").mock(
        return_value=ics_error(409, "external_ref_exists")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp, "ics_task_link", {"slug_or_id": ASSET_ID, "wp": "4711", "role": "context"}
        )
    err = error_payload(exc)
    assert err["code"] == "external_ref_exists"
    assert err["status"] == 409
    assert "ics_asset_external_refs" in err["hint"]


# ------------------------------- ics_task_unlink -------------------------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_task_unlink_dry_run_does_not_call_ics(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, tasks)
    respx_mock.get(f"{ICS}/api/external-refs/{REF_ID}").mock(
        return_value=ics_error(404, "external_ref_not_found")
    )
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    route = respx_mock.delete(f"{ICS}/api/external-refs/{REF_ID}").mock(
        return_value=httpx.Response(200, json={"deleted": True})
    )
    payload = await call_tool(mcp, "ics_task_unlink", {"ref_id": REF_ID})
    assert payload["action"] == "unlink_task"
    assert payload["target"] == f"task link {REF_ID}"
    assert not route.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_task_unlink_preview_names_document_and_task(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, tasks)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    respx_mock.get(f"{ICS}/api/external-refs/{REF_ID}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": REF_ID,
                "asset": {"slug": "spec-v2", "title": "Spec v2"},
                "system": "openproject",
                "external_id": "4712",
                "external_scope": "portal",
                "role": "context",
                "required": True,
                "label": "Account page",
            },
        )
    )
    payload = await call_tool(mcp, "ics_task_unlink", {"ref_id": REF_ID})
    assert payload["target"] == (
        f"task link {REF_ID}: 'Spec v2' (spec-v2) as context, required of "
        "openproject 4712 in portal ('Account page')"
    )


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_task_unlink_yolo_deletes(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, tasks)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    route = respx_mock.delete(f"{ICS}/api/external-refs/{REF_ID}").mock(
        return_value=httpx.Response(200, json={"deleted": True})
    )
    payload = await call_tool(mcp, "ics_task_unlink", {"ref_id": REF_ID})
    assert payload == {"deleted": True}
    assert route.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_task_unlink_confirm_false_refuses(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, tasks)
    respx_mock.get(f"{ICS}/api/external-refs/{REF_ID}").mock(
        return_value=ics_error(404, "external_ref_not_found")
    )
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    route = respx_mock.delete(f"{ICS}/api/external-refs/{REF_ID}")
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_task_unlink", {"ref_id": REF_ID, "confirm": False})
    assert error_payload(exc)["code"] == "confirm_required"
    assert not route.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_task_unlink_404(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    respx_mock.delete(f"{ICS}/api/external-refs/{REF_ID}").mock(
        return_value=ics_error(404, "external_ref_not_found")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_task_unlink", {"ref_id": REF_ID, "confirm": True})
    assert error_payload(exc)["code"] == "external_ref_not_found"


# ---------------------------- ics_asset_external_refs ----------------------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_external_refs_lists(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    mock_resolve(respx_mock)
    respx_mock.get(f"{ICS}/api/assets/{ASSET_ID}/external-refs").mock(
        return_value=httpx.Response(200, json=[ext_ref(), ext_ref(id=KEY_ID, role="reference")])
    )
    payload = await call_tool(mcp, "ics_asset_external_refs", {"slug_or_id": "abc"})
    assert payload["asset"] == {"slug": "abc"}
    assert [r["role"] for r in payload["refs"]] == ["context", "reference"]
    assert not {"asset_id", "entity", "url", "origin", "created_at"} & set(payload["refs"][0])
    assert "note" not in payload["refs"][0]
    assert "truncated" not in payload


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_external_refs_cut_to_limit(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    mock_meta(respx_mock)
    refs = [ext_ref(id=f"r{i}", external_id=str(i), note="n" * 200) for i in range(100)]
    respx_mock.get(f"{ICS}/api/assets/{ASSET_ID}/external-refs").mock(
        return_value=httpx.Response(200, json=refs)
    )
    payload = await call_tool(mcp, "ics_asset_external_refs", {"slug_or_id": ASSET_ID})
    assert payload["truncated"] is True
    assert payload["refs"][0]["id"] == "r0"
    assert payload["omitted"] == len(refs) - len(payload["refs"])
    assert payload_chars(payload) <= 8000


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_external_refs_no_graph_access(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    mock_meta(respx_mock)
    respx_mock.get(f"{ICS}/api/assets/{ASSET_ID}/external-refs").mock(
        return_value=ics_error(404, "asset_not_found")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_external_refs", {"slug_or_id": ASSET_ID})
    err = error_payload(exc)
    assert err["code"] == "asset_not_found"
    assert "graph access" in err["hint"]


# ------------------------------- ics_project_links -------------------------------


def key_doc(asset_id: str = KEY_ID, position: int = 0) -> dict[str, Any]:
    return {
        "id": asset_id,
        "slug": "charter",
        "title": "Project charter",
        "asset_id": asset_id,
        "position": position,
        "reason": "project charter",
    }


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_project_links_reads(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    ext = respx_mock.get(f"{ICS}/api/projects/acme/external-refs").mock(
        return_value=httpx.Response(
            200, json=[{"system": "openproject", "external_id": "acme-app"}]
        )
    )
    keys = respx_mock.get(f"{ICS}/api/projects/acme/key-documents").mock(
        return_value=httpx.Response(200, json=[key_doc()])
    )
    put = respx_mock.put(url__startswith=f"{ICS}/api/projects/acme/")
    payload = await call_tool(mcp, "ics_project_links", {"project_slug": "acme"})
    assert ext.called and keys.called and not put.called
    assert payload["project_slug"] == "acme"
    assert payload["external_refs"][0]["external_id"] == "acme-app"
    assert payload["key_documents"][0]["reason"] == "project charter"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_project_links_are_compact(real_client, respx_mock, make_mcp):
    """Key documents by slug like list items: no id/asset_id pair, no
    position, no md_single kind, no current freshness, no nulls."""
    mcp = make_mcp(tasks)
    respx_mock.get(f"{ICS}/api/projects/acme/external-refs").mock(
        return_value=httpx.Response(200, json=[{"system": "openproject", "external_id": "acme"}])
    )
    full = {
        **key_doc(),
        "kind": "md_single",
        "doc_type": "policy",
        "freshness": "review_overdue",
        "superseded_by": None,
        "summary": "How long we keep invoices.",
        "estimated_tokens": 69,
    }
    respx_mock.get(f"{ICS}/api/projects/acme/key-documents").mock(
        return_value=httpx.Response(200, json=[full])
    )
    payload = await call_tool(mcp, "ics_project_links", {"project_slug": "acme"})
    assert payload["key_documents"] == [
        {
            "slug": "charter",
            "title": "Project charter",
            "doc_type": "policy",
            "freshness": "review_overdue",
            "summary": "How long we keep invoices.",
            "estimated_tokens": 69,
            "reason": "project charter",
        }
    ]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_project_links_sets_both(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    mock_resolve(respx_mock, slug="charter", asset_id=KEY_ID)
    refs = [
        {"system": "openproject", "external_id": "acme-app"},
        {"system": "project_standard", "external_id": "ps-acme"},
    ]
    ext = respx_mock.put(f"{ICS}/api/projects/acme/external-refs").mock(
        return_value=httpx.Response(200, json=refs)
    )
    keys = respx_mock.put(f"{ICS}/api/projects/acme/key-documents").mock(
        return_value=httpx.Response(200, json=[key_doc(), key_doc(ASSET_ID, 1)])
    )
    payload = await call_tool(
        mcp,
        "ics_project_links_set",
        {
            "project_slug": "acme",
            "confirm": True,
            "set_external": refs,
            "key_documents": [
                {"slug_or_id": "charter", "reason": "project charter"},
                {"slug_or_id": ASSET_ID},
            ],
        },
    )
    assert json.loads(ext.calls[0].request.content) == {"refs": refs}
    assert json.loads(keys.calls[0].request.content) == {
        "documents": [
            {"asset_id": KEY_ID, "reason": "project charter"},
            {"asset_id": ASSET_ID, "reason": None},
        ]
    }
    assert len(payload["external_refs"]) == 2
    assert payload["key_documents"] == [
        {"slug": "charter", "title": "Project charter", "reason": "project charter"},
        {"slug": "charter", "title": "Project charter", "reason": "project charter"},
    ]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_project_links_clears_with_empty_list(real_client, respx_mock, make_mcp):
    """`[]` clears a list, but only with an explicit confirm=true: yolo alone
    is refused, dry_run previews."""
    mcp = make_mcp(session_tool, tasks)
    ext = respx_mock.put(f"{ICS}/api/projects/acme/external-refs").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(f"{ICS}/api/projects/acme/key-documents").mock(
        return_value=httpx.Response(200, json=[])
    )
    args = {"project_slug": "acme", "key_documents": [], "set_external": []}
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_project_links_set", args)
    assert error_payload(exc)["code"] == "confirm_required"
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    preview = await call_tool(mcp, "ics_project_links_set", args)
    assert preview["target"] == "project acme: clear external projects; clear key documents"
    assert not ext.called
    keys_put = respx_mock.put(f"{ICS}/api/projects/acme/key-documents").mock(
        return_value=httpx.Response(200, json=[])
    )
    payload = await call_tool(mcp, "ics_project_links_set", {**args, "confirm": True})
    assert json.loads(ext.calls[0].request.content) == {"refs": []}
    assert json.loads(keys_put.calls[0].request.content) == {"documents": []}
    assert payload["external_refs"] == []


@pytest.mark.asyncio
@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_project_links_set_follows_the_session_mode(real_client, respx_mock, make_mcp):
    """A write in the default (interactive) mode without elicitation asks
    for confirmation and sends nothing; a call with nothing to set is bad input."""
    mcp = make_mcp(tasks)
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_project_links_set",
            {
                "project_slug": "acme",
                "set_external": [{"system": "openproject", "external_id": "x"}],
            },
        )
    assert error_payload(exc)["code"] == "confirm_required"
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_project_links_set", {"project_slug": "acme", "confirm": True})
    assert error_payload(exc)["code"] == "invalid_argument"
    assert respx_mock.calls.call_count == 0


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_project_links_external_taken(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    respx_mock.put(f"{ICS}/api/projects/acme/external-refs").mock(
        return_value=ics_error(409, "project_external_taken")
    )
    keys = respx_mock.get(f"{ICS}/api/projects/acme/key-documents")
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_project_links_set",
            {
                "project_slug": "acme",
                "confirm": True,
                "set_external": [{"system": "openproject", "external_id": "acme-app"}],
            },
        )
    err = error_payload(exc)
    assert err["code"] == "project_external_taken"
    assert err["status"] == 409
    assert "ICS home" in err["hint"]
    assert not keys.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_project_links_not_owner(real_client, respx_mock, make_mcp):
    mcp = make_mcp(tasks)
    respx_mock.get(f"{ICS}/api/projects/acme/external-refs").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.put(f"{ICS}/api/projects/acme/key-documents").mock(
        return_value=ics_error(403, "project_role_required")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_project_links_set",
            {"project_slug": "acme", "key_documents": [{"slug_or_id": ASSET_ID}], "confirm": True},
        )
    assert error_payload(exc)["code"] == "project_role_required"


# ------------------------------------- help -------------------------------------


@pytest.mark.asyncio
async def test_task_context_help_topic(make_mcp):
    mcp = make_mcp(session_tool)
    payload = await call_tool(mcp, "ics_help", {"topic": "task-context"})
    content = payload["content_markdown"]
    assert "ics_task_context" in content
    assert "project_external_taken" in content
