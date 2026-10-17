"""Relation graph tools (ICS ADR-0016). Response mocks follow the ICS contract
(`services/relation_views.py`, `services/relation_graph.py`)."""

from __future__ import annotations

import json
from typing import Any, get_args

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from ics_mcp import models as M
from ics_mcp.config import get_settings
from ics_mcp.tools import relations
from ics_mcp.tools import session as session_tool
from tests.conftest import ASSET_ID, ICS, call_tool, mock_resolve

REL_ID = "44444444-4444-4444-4444-444444444444"
TARGET_ID = "55555555-5555-5555-5555-555555555555"


def node(i: int, depth: int = 1, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f"00000000-0000-0000-0000-{i:012d}",
        "slug": f"doc-{i}",
        "title": f"Document {i}",
        "kind": "md_single",
        "doc_type": "specification",
        "freshness": "current",
        "summary": "What the document is for. " * 8,
        "estimated_tokens": 1200,
        "depth": depth,
        "expandable": True,
    }
    base.update(overrides)
    return base


def edge(source_id: str = ASSET_ID, target_id: str = TARGET_ID, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": REL_ID,
        "relation_type": "derived_from",
        "source_id": source_id,
        "target_id": target_id,
        "source_path": None,
        "target_path": None,
        "target_anchor": None,
        "target_version": 1,
        "target_version_now": 1,
        "target_changed": False,
        "note": None,
        "origin": "agent",
        "created_at": "2026-09-26T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def ics_error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"detail": code.replace("_", " "), "code": code})


def error_payload(exc: pytest.ExceptionInfo[ToolError]) -> dict[str, Any]:
    return json.loads(str(exc.value))


# ----------------------------- ics_asset_relations -----------------------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_relations_passes_filters(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    body = {
        "asset_id": ASSET_ID,
        "outgoing": {"derived_from": [{**edge(), "other": node(1), "label": "derived_from"}]},
        "incoming": {},
    }
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/relations").mock(
        return_value=httpx.Response(200, json=body)
    )
    payload = await call_tool(
        mcp,
        "ics_asset_relations",
        {"slug_or_id": "abc", "types": ["derived_from", "supersedes"], "direction": "out"},
    )
    params = route.calls[0].request.url.params
    assert params.get_list("types") == ["derived_from", "supersedes"]
    assert params["direction"] == "out"
    assert payload["outgoing"]["derived_from"][0]["other"]["slug"] == "doc-1"
    assert "truncated" not in payload


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_relations_404_is_asset_not_found(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/relations").mock(
        return_value=ics_error(404, "asset_not_found")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_relations", {"slug_or_id": "abc"})
    err = error_payload(exc)
    assert err["code"] == "asset_not_found"
    assert err["status"] == 404
    assert "graph access" in err["hint"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_relations_truncated_to_limit(real_client, respx_mock, make_mcp, monkeypatch):
    monkeypatch.setattr(get_settings(), "mcp_response_max_chars", 4000)
    mcp = make_mcp(relations)
    items = [{**edge(id=f"r{i}"), "other": node(i), "label": "depends_on"} for i in range(1, 30)]
    body = {"asset_id": ASSET_ID, "outgoing": {"depends_on": items}, "incoming": {}}
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/relations").mock(
        return_value=httpx.Response(200, json=body)
    )
    payload = await call_tool(mcp, "ics_asset_relations", {"slug_or_id": "abc"})
    kept = payload["outgoing"]["depends_on"]
    assert payload["truncated"] is True
    assert 0 < len(kept) < len(items)
    assert payload["omitted_edges"] == len(items) - len(kept)
    assert kept[0]["id"] == "r1"
    assert "types" in payload["hint"]
    assert len(json.dumps(payload)) <= 4000


# ------------------------------- ics_relation_add -------------------------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_add_by_slug(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    mock_resolve(respx_mock)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/relations").mock(
        return_value=httpx.Response(201, json=edge(note="Built from the goals."))
    )
    payload = await call_tool(
        mcp,
        "ics_relation_add",
        {
            "source": "abc",
            "target": "goals",
            "relation_type": "derived_from",
            "target_anchor": "scope",
            "note": "Built from the goals.",
            "confirm": True,
        },
    )
    assert json.loads(route.calls[0].request.content) == {
        "relation_type": "derived_from",
        "target_slug": "goals",
        "target_anchor": "scope",
        "note": "Built from the goals.",
    }
    assert route.calls[0].request.url.params["shape"] == "compact"
    assert payload["id"] == REL_ID


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_add_returns_the_compact_edge_and_remembers_it(
    real_client, respx_mock, make_mcp
):
    mcp = make_mcp(session_tool, relations)
    mock_resolve(respx_mock)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/relations").mock(
        return_value=httpx.Response(201, json=compact_single())
    )
    payload = await call_tool(
        mcp,
        "ics_relation_add",
        {"source": "abc", "target": "goals", "relation_type": "derived_from", "confirm": True},
    )
    assert payload["edge"][:3] == ["abc", "derived_from", "goals"]
    assert payload["nodes"]["goals"]["title"] == "Goals"
    # ICS answers 404 for the relation: the preview uses what the add returned.
    respx_mock.get(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=ics_error(404, "relation_not_found")
    )
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    preview = await call_tool(mcp, "ics_relation_remove", {"relation_id": REL_ID})
    assert preview["target"] == (
        f"relation {REL_ID}: 'Design' (abc) derived_from 'Goals' (goals)#scope"
    )


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_add_uuid_target_sends_target_id(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/relations").mock(
        return_value=httpx.Response(201, json=edge())
    )
    await call_tool(
        mcp,
        "ics_relation_add",
        {"source": ASSET_ID, "target": TARGET_ID, "relation_type": "supersedes", "confirm": True},
    )
    assert json.loads(route.calls[0].request.content) == {
        "relation_type": "supersedes",
        "target_id": TARGET_ID,
    }


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_add_cycle_is_promoted(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/relations").mock(
        return_value=ics_error(409, "relation_cycle")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_relation_add",
            {"source": ASSET_ID, "target": "older", "relation_type": "supersedes", "confirm": True},
        )
    err = error_payload(exc)
    assert err["code"] == "relation_cycle"
    assert err["status"] == 409
    assert "cycle" in err["hint"]


@pytest.mark.parametrize(
    ("code", "key", "values"),
    [
        ("relation_target_anchor_not_found", "anchors", ["scope", "endpoints"]),
        ("relation_target_path_not_found", "paths", ["index.md", "api.md"]),
    ],
)
@pytest.mark.asyncio
async def test_relation_add_missing_location_lists_what_exists(
    real_client, respx_mock, make_mcp, code, key, values
):
    """ICS names the anchors (or files) of the target; they reach `data`, so
    the agent can retry without reading the outline first."""
    mcp = make_mcp(relations)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/relations").mock(
        return_value=httpx.Response(400, json={"detail": "not found", "code": code, key: values})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_relation_add",
            {
                "source": ASSET_ID,
                "target": "spec",
                "relation_type": "derived_from",
                "target_anchor": "Endpointz",
                "confirm": True,
            },
        )
    err = error_payload(exc)
    assert err["code"] == code
    assert err["data"][key] == values
    assert f"data.{key}" in err["hint"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_add_unknown_target_404(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/relations").mock(
        return_value=ics_error(404, "asset_not_found")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_relation_add",
            {
                "source": ASSET_ID,
                "target": "hidden",
                "relation_type": "depends_on",
                "confirm": True,
            },
        )
    assert error_payload(exc)["code"] == "asset_not_found"


@pytest.mark.asyncio
async def test_relation_add_rejects_unknown_type_locally(real_client, make_mcp):
    mcp = make_mcp(relations)
    with pytest.raises(ValidationError):
        await call_tool(
            mcp,
            "ics_relation_add",
            {"source": ASSET_ID, "target": "x", "relation_type": "blocks"},
        )


# ------------------------------ ics_relation_update ------------------------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_update_refresh_and_clear_note(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    route = respx_mock.patch(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=httpx.Response(200, json=edge(target_version=2, target_version_now=2))
    )
    payload = await call_tool(
        mcp,
        "ics_relation_update",
        {"relation_id": REL_ID, "note": "", "refresh_target_version": True},
    )
    assert json.loads(route.calls[0].request.content) == {
        "note": None,
        "refresh_target_version": True,
    }
    assert route.calls[0].request.url.params["shape"] == "compact"
    assert payload["target_changed"] is False


@pytest.mark.asyncio
async def test_relation_update_without_changes_is_invalid_argument(real_client, make_mcp):
    mcp = make_mcp(relations)
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_relation_update", {"relation_id": REL_ID})
    assert error_payload(exc)["code"] == "invalid_argument"
    assert error_payload(exc)["field"] == "note"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_update_404(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.patch(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=ics_error(404, "relation_not_found")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_relation_update", {"relation_id": REL_ID, "note": "x"})
    assert error_payload(exc)["code"] == "relation_not_found"


# ------------------------------ ics_relation_remove ------------------------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_remove_dry_run_does_not_call_ics(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, relations)
    respx_mock.get(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=ics_error(404, "relation_not_found")
    )
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    route = respx_mock.delete(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=httpx.Response(200, json={"deleted": True})
    )
    payload = await call_tool(mcp, "ics_relation_remove", {"relation_id": REL_ID})
    assert payload["action"] == "remove_relation"
    assert payload["target"].startswith(f"relation {REL_ID} (its ends are unknown")
    assert not route.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_remove_preview_names_the_ends_seen_in_a_listing(
    real_client, respx_mock, make_mcp
):
    """ICS cannot read one relation by id, so the preview names the ends the
    session saw in `ics_asset_relations`."""
    mcp = make_mcp(session_tool, relations)
    respx_mock.get(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=ics_error(404, "relation_not_found")
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/relations").mock(
        return_value=httpx.Response(
            200,
            json={
                "asset_id": ASSET_ID,
                "outgoing": {
                    "derived_from": [
                        {
                            **edge(target_anchor="scope"),
                            "other": {"id": TARGET_ID, "slug": "goals", "title": "Goals"},
                        }
                    ]
                },
                "incoming": {},
            },
        )
    )
    await call_tool(mcp, "ics_asset_relations", {"slug_or_id": "abc", "detail": "full"})
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    route = respx_mock.delete(f"{ICS}/api/relations/{REL_ID}")
    payload = await call_tool(mcp, "ics_relation_remove", {"relation_id": REL_ID})
    assert payload["target"] == f"relation {REL_ID}: abc derived_from goals#scope"
    assert not route.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_remove_preview_names_the_ends_of_a_compact_listing(
    real_client, respx_mock, make_mcp
):
    mcp = make_mcp(session_tool, relations)
    respx_mock.get(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=ics_error(404, "relation_not_found")
    )
    compact_edge = ["abc", "depends_on", "goals", {"id": REL_ID, "target_anchor": "scope"}]
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/relations").mock(
        return_value=httpx.Response(
            200,
            json={"asset": "abc", "nodes": {"goals": {"title": "Goals"}}, "edges": [compact_edge]},
        )
    )
    await call_tool(mcp, "ics_asset_relations", {"slug_or_id": "abc"})
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    payload = await call_tool(mcp, "ics_relation_remove", {"relation_id": REL_ID})
    assert payload["target"] == f"relation {REL_ID}: abc depends_on goals#scope"


def compact_single(**extra: Any) -> dict[str, Any]:
    """ICS `GET /api/relations/{id}` and relation writes with `shape=compact`."""
    return {
        "edge": ["abc", "derived_from", "goals", {"id": REL_ID, "target_anchor": "scope", **extra}],
        "nodes": {
            "abc": {"title": "Design", "doc_type": "design"},
            "goals": {"title": "Goals", "freshness": "review_overdue"},
        },
    }


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_remove_preview_reads_the_relation_by_id(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, relations)
    respx_mock.get(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=httpx.Response(200, json=compact_single())
    )
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    payload = await call_tool(mcp, "ics_relation_remove", {"relation_id": REL_ID})
    assert payload["target"] == (
        f"relation {REL_ID}: 'Design' (abc) derived_from 'Goals' (goals)#scope"
    )


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_add_dry_run_previews_by_title(real_client, respx_mock, make_mcp):
    """dry_run writes nothing and names source, type and target by title."""
    mcp = make_mcp(session_tool, relations)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "dry_run"})
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "slug": "abc", "title": "Design"})
    )
    respx_mock.get(f"{ICS}/api/assets/{TARGET_ID}").mock(
        return_value=httpx.Response(200, json={"id": TARGET_ID, "slug": "goals", "title": "Goals"})
    )
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/relations")
    payload = await call_tool(
        mcp,
        "ics_relation_add",
        {
            "source": "abc",
            "target": TARGET_ID,
            "relation_type": "derived_from",
            "target_anchor": "scope",
        },
    )
    assert payload["action"] == "add_relation"
    assert payload["target"] == "'Design' (abc) derived_from 'Goals' (goals)#scope"
    assert not route.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_add_default_mode_needs_confirmation(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    mock_resolve(respx_mock)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/relations")
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_relation_add",
            {"source": "abc", "target": "abc", "relation_type": "supersedes"},
        )
    assert error_payload(exc)["code"] == "confirm_required"
    assert not route.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_remove_yolo_deletes(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, relations)
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    route = respx_mock.delete(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=httpx.Response(200, json={"deleted": True})
    )
    payload = await call_tool(mcp, "ics_relation_remove", {"relation_id": REL_ID})
    assert payload == {"deleted": True}
    assert route.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_remove_confirm_false_refuses(real_client, respx_mock, make_mcp):
    mcp = make_mcp(session_tool, relations)
    respx_mock.get(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=ics_error(404, "relation_not_found")
    )
    await call_tool(mcp, "ics_session_set_mode", {"mode": "yolo"})
    route = respx_mock.delete(f"{ICS}/api/relations/{REL_ID}")
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_relation_remove", {"relation_id": REL_ID, "confirm": False})
    assert error_payload(exc)["code"] == "confirm_required"
    assert not route.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_remove_default_mode_without_confirm_deletes_nothing(
    real_client, respx_mock, make_mcp
):
    """The default session mode asks the client; a client that cannot answer
    gets `confirm_required` and ICS is never called."""
    assert get_settings().mcp_default_confirm == "interactive"
    mcp = make_mcp(relations)
    respx_mock.get(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=ics_error(404, "relation_not_found")
    )
    route = respx_mock.delete(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=httpx.Response(200, json={"deleted": True})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_relation_remove", {"relation_id": REL_ID})
    assert error_payload(exc)["code"] == "confirm_required"
    assert not route.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_relation_remove_404(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.delete(f"{ICS}/api/relations/{REL_ID}").mock(
        return_value=ics_error(404, "relation_not_found")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_relation_remove", {"relation_id": REL_ID, "confirm": True})
    assert error_payload(exc)["code"] == "relation_not_found"


# ---------------------------- ics_graph_neighbourhood ----------------------------


def neighbourhood_body(n: int, *, truncated: bool = False) -> dict[str, Any]:
    root = node(0, depth=0)
    nodes = [root] + [node(i, depth=1 if i <= n // 2 else 2) for i in range(1, n + 1)]
    edges = [edge(root["id"], nodes[i]["id"], id=f"e{i}") for i in range(1, n + 1)]
    return {
        "root_id": root["id"],
        "depth": 2,
        "types": ["depends_on", "derived_from", "part_of", "supersedes", "contradicts"],
        "nodes": nodes,
        "edges": edges,
        "truncated": truncated,
        "max_nodes": 50,
    }


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_neighbourhood_passes_params(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/neighbourhood").mock(
        return_value=httpx.Response(200, json=neighbourhood_body(2))
    )
    payload = await call_tool(
        mcp,
        "ics_graph_neighbourhood",
        {"slug_or_id": "abc", "depth": 2, "types": ["references"], "max_nodes": 10},
    )
    params = route.calls[0].request.url.params
    assert params["depth"] == "2"
    assert params.get_list("types") == ["references"]
    assert params["max_nodes"] == "10"
    assert params["shape"] == "compact"
    assert params["direction"] == "both"
    assert len(payload["nodes"]) == 3
    assert payload["truncated"] is False
    assert "hint" not in payload


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_neighbourhood_depth_two_keeps_freshness_and_edge_types(
    real_client, respx_mock, make_mcp
):
    mcp = make_mcp(relations)
    root = node(0, depth=0)
    near = node(1, depth=1, freshness="review_overdue")
    far = node(2, depth=2, freshness="superseded")
    body = {
        "root_id": root["id"],
        "depth": 2,
        "types": ["derived_from", "supersedes"],
        "nodes": [root, near, far],
        "edges": [
            edge(root["id"], near["id"], id="e1", relation_type="derived_from"),
            edge(far["id"], near["id"], id="e2", relation_type="supersedes"),
        ],
        "truncated": False,
        "max_nodes": 50,
    }
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/neighbourhood").mock(
        return_value=httpx.Response(200, json=body)
    )
    payload = await call_tool(mcp, "ics_graph_neighbourhood", {"slug_or_id": "abc", "depth": 2})
    assert route.calls[0].request.url.params["depth"] == "2"
    assert [(n["depth"], n["freshness"]) for n in payload["nodes"]] == [
        (0, "current"),
        (1, "review_overdue"),
        (2, "superseded"),
    ]
    assert [e["relation_type"] for e in payload["edges"]] == ["derived_from", "supersedes"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_neighbourhood_uuid_resolves_slug(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.get(f"{ICS}/api/assets/{ASSET_ID}").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "slug": "abc"})
    )
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/neighbourhood").mock(
        return_value=httpx.Response(200, json=neighbourhood_body(1))
    )
    await call_tool(mcp, "ics_graph_neighbourhood", {"slug_or_id": ASSET_ID})
    assert route.calls[0].request.url.params["depth"] == "1"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_neighbourhood_ics_cut_gets_hint(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/neighbourhood").mock(
        return_value=httpx.Response(200, json=neighbourhood_body(1, truncated=True))
    )
    payload = await call_tool(mcp, "ics_graph_neighbourhood", {"slug_or_id": "abc"})
    assert payload["truncated"] is True
    assert "max_nodes" in payload["hint"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_neighbourhood_truncated_keeps_nearest(
    real_client, respx_mock, make_mcp, monkeypatch
):
    monkeypatch.setattr(get_settings(), "mcp_response_max_chars", 5000)
    mcp = make_mcp(relations)
    body = neighbourhood_body(30)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/neighbourhood").mock(
        return_value=httpx.Response(200, json=body)
    )
    payload = await call_tool(
        mcp,
        "ics_graph_neighbourhood",
        {"slug_or_id": "abc", "depth": 2, "detail": "full", "max_nodes": 3},
    )
    kept = payload["nodes"]
    ids = {n["id"] for n in kept}
    assert payload["truncated"] is True
    assert kept == body["nodes"][: len(kept)]
    assert payload["omitted_nodes"] == len(body["nodes"]) - len(kept)
    assert all(e["source_id"] in ids and e["target_id"] in ids for e in payload["edges"])
    assert "depth" in payload["hint"] and "direction" in payload["hint"]
    assert len(json.dumps(payload)) <= 5000


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_neighbourhood_404(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/neighbourhood").mock(
        return_value=ics_error(404, "asset_not_found")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_graph_neighbourhood", {"slug_or_id": "abc"})
    assert error_payload(exc)["code"] == "asset_not_found"


def compact_body(n: int, **extra: Any) -> dict[str, Any]:
    """A compact neighbourhood: root, then n nodes, half at depth 2."""
    nodes: dict[str, Any] = {"doc-0": {"title": "Root", "depth": 0}}
    edges: list[Any] = []
    for i in range(1, n + 1):
        depth = 1 if i <= n // 2 else 2
        nodes[f"doc-{i}"] = {
            "title": f"Document {i}",
            "doc_type": "specification",
            "summary": "What the document is for. " * 6,
            "estimated_tokens": 1200,
            "depth": depth,
        }
        src = "doc-0" if depth == 1 else f"doc-{i - n // 2}"
        edges.append([f"doc-{i}", "derived_from" if i % 2 else "depends_on", src])
    return {
        "root": "doc-0",
        "depth": 2,
        "types": ["depends_on", "derived_from"],
        "nodes": nodes,
        "edges": edges,
        "max_nodes": 20,
        **extra,
    }


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_neighbourhood_compact_depth_two_fits_by_default(
    real_client, respx_mock, make_mcp, monkeypatch
):
    monkeypatch.setattr(get_settings(), "mcp_response_max_chars", 5000)
    body = compact_body(19)
    assert len(json.dumps(body)) > get_settings().mcp_response_max_chars
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/neighbourhood").mock(
        return_value=httpx.Response(200, json=body)
    )
    payload = await call_tool(
        make_mcp(relations), "ics_graph_neighbourhood", {"slug_or_id": "abc", "depth": 2}
    )
    # The limit follows max_nodes (default 20), so the whole depth 2 comes back.
    assert route.calls[0].request.url.params["max_nodes"] == "20"
    assert payload == body


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_neighbourhood_compact_cut_names_a_working_next_step(
    real_client, respx_mock, make_mcp, monkeypatch
):
    monkeypatch.setattr(get_settings(), "mcp_response_max_chars", 2000)
    body = compact_body(19)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/neighbourhood").mock(
        return_value=httpx.Response(200, json=body)
    )
    payload = await call_tool(
        make_mcp(relations),
        "ics_graph_neighbourhood",
        {"slug_or_id": "abc", "depth": 2, "max_nodes": 4},
    )
    kept = list(payload["nodes"])
    assert kept == list(body["nodes"])[: len(kept)]
    assert all(e[0] in kept and e[2] in kept for e in payload["edges"])
    hint = payload["hint"]
    assert "depends_on x" in hint and "derived_from x" in hint
    assert "direction='out'" in hint
    assert f"slug_or_id='{kept[-1]}'" in hint
    assert len(json.dumps(payload, separators=(",", ":"))) <= 2250


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_asset_relations_compact_cut_keeps_nodes_of_kept_edges(
    real_client, respx_mock, make_mcp, monkeypatch
):
    monkeypatch.setattr(get_settings(), "mcp_response_max_chars", 1500)
    nodes = {f"doc-{i}": {"title": f"Document {i}", "summary": "x" * 100} for i in range(20)}
    edges = [["abc", "depends_on", f"doc-{i}", {"id": f"r{i}"}] for i in range(20)]
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/relations").mock(
        return_value=httpx.Response(200, json={"asset": "abc", "nodes": nodes, "edges": edges})
    )
    payload = await call_tool(make_mcp(relations), "ics_asset_relations", {"slug_or_id": "abc"})
    assert route.calls[0].request.url.params["shape"] == "compact"
    assert payload["edges"] == edges[: len(payload["edges"])]
    assert set(payload["nodes"]) == {e[2] for e in payload["edges"]}
    assert payload["omitted_edges"] == 20 - len(payload["edges"])


@pytest.mark.asyncio
async def test_neighbourhood_depth_is_capped(real_client, make_mcp):
    mcp = make_mcp(relations)
    with pytest.raises(ValidationError):
        await call_tool(mcp, "ics_graph_neighbourhood", {"slug_or_id": "abc", "depth": 4})


@pytest.mark.asyncio
async def test_graph_help_topic(make_mcp):
    mcp = make_mcp(session_tool)
    payload = await call_tool(mcp, "ics_help", {"topic": "graph"})
    assert "derived_from" in payload["content_markdown"]
    assert "Graphs are independent" in payload["content_markdown"]


@pytest.mark.asyncio
async def test_graph_help_describes_every_relation_type(make_mcp):
    mcp = make_mcp(session_tool)
    content = (await call_tool(mcp, "ics_help", {"topic": "graph"}))["content_markdown"]
    table = content.split("## Relation types", 1)[1].split("\n## ", 1)[0]
    for relation_type in get_args(M.RelationType.__value__):
        assert f"| `{relation_type}` |" in table, relation_type


# ---------------------------- skipped edges and rescan ----------------------------


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_neighbourhood_names_skipped_content_links(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/neighbourhood").mock(
        return_value=httpx.Response(
            200,
            json={
                "root": "abc",
                "depth": 1,
                "types": ["contradicts", "depends_on", "derived_from", "part_of", "supersedes"],
                "nodes": {"abc": {"title": "Root", "depth": 0}},
                "edges": [],
                "max_nodes": 20,
                "skipped": {"references": 2},
            },
        )
    )
    payload = await call_tool(mcp, "ics_graph_neighbourhood", {"slug_or_id": "abc"})
    assert payload["skipped"] == {"references": 2}
    assert "references x2" in payload["hint"]
    assert "types" in payload["hint"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_neighbourhood_without_skipped_has_no_hint(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/neighbourhood").mock(
        return_value=httpx.Response(200, json=neighbourhood_body(2))
    )
    payload = await call_tool(mcp, "ics_graph_neighbourhood", {"slug_or_id": "abc"})
    assert "hint" not in payload


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_rescan_posts_by_id_and_returns_edges(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "slug": "abc"})
    )
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/relations/rescan").mock(
        return_value=httpx.Response(
            200,
            json={
                "asset": "abc",
                "added": 1,
                "removed": 0,
                "nodes": {"tgt": {"title": "Target"}},
                "edges": [["abc", "references", "tgt"]],
            },
        )
    )
    payload = await call_tool(mcp, "ics_asset_rescan_relations", {"slug_or_id": "abc"})
    assert route.called
    assert payload["added"] == 1
    assert payload["edges"] == [["abc", "references", "tgt"]]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_rescan_without_editor_explains_the_role(real_client, respx_mock, make_mcp):
    mcp = make_mcp(relations)
    respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/relations/rescan").mock(
        return_value=ics_error(404, "asset_not_found")
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_rescan_relations", {"slug_or_id": ASSET_ID})
    err = error_payload(exc)
    assert err["code"] == "asset_not_found"
    assert "editor" in err["hint"]
