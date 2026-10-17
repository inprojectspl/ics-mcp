"""Freshness (ICS ADR-0015), compact outgoing relations (ADR-0016, section
10), heading limits, trimming and anchor reads in `ics_asset_outline` and
`ics_asset_read`. Mocks follow the ICS contract (`routes/mcp_assets/outline.py`,
`routes/mcp_assets/partial_read.py`)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import jsonschema
import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp._payload import payload_chars
from ics_mcp.config import get_settings
from ics_mcp.tools import discovery, read
from tests.conftest import ICS, call_tool

SUCCESSOR = {"id": "66666666-6666-6666-6666-666666666666", "slug": "spec-v2", "title": "Spec v2"}


def outline(**extra: Any) -> dict[str, Any]:
    return {
        "items": [{"title": "Scope", "level": 1}],
        "summary": "Booking API, first draft.",
        "freshness": "current",
        "superseded_by": None,
        **extra,
    }


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_superseded_read_names_successor_before_content(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v1/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "spec-v1",
                "path": "doc.md",
                "content": "# Spec v1\nbody\n",
                "total_lines": 2,
                "returned_range": [1, 2],
                "version": 1,
                "current_version": 1,
                "freshness": "superseded",
                "superseded_by": SUCCESSOR,
            },
        )
    )
    payload = await call_tool(make_mcp(read), "ics_asset_read", {"slug_or_id": "spec-v1"})

    assert payload["freshness"] == "superseded"
    assert payload["superseded_by"] == "spec-v2"
    assert "Spec v2" in payload["notice"]
    assert "Prefer the successor" in payload["notice"]
    keys = list(payload)
    assert keys.index("notice") < keys.index("content")
    assert keys.index("superseded_by") < keys.index("content")


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_read_notice_points_at_the_end_of_the_chain(real_client, respx_mock, make_mcp):
    """The direct successor is superseded too: the notice names `latest`."""
    respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v1/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "spec-v1",
                "path": "doc.md",
                "content": "# Spec v1\n",
                "freshness": "superseded",
                "superseded_by": SUCCESSOR,
                "latest": "spec-v3",
            },
        )
    )
    payload = await call_tool(make_mcp(read), "ics_asset_read", {"slug_or_id": "spec-v1"})
    assert payload["latest"] == "spec-v3"
    assert "`spec-v3`" in payload["notice"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_read_of_a_chain_start_names_the_current_version(real_client, respx_mock, make_mcp):
    """v1 -> v2 -> v3: ICS names v2 as the direct successor and v3 as `latest`;
    the notice sends the agent to v3, not to the superseded v2."""
    respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v1/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "spec-v1",
                "path": "doc.md",
                "content": "# Spec v1\n",
                "freshness": "superseded",
                "superseded_by": SUCCESSOR,
                "latest": "spec-v3",
                "version": 1,
                "current_version": 1,
            },
        )
    )
    payload = await call_tool(make_mcp(read), "ics_asset_read", {"slug_or_id": "spec-v1"})
    assert payload["superseded_by"] == "spec-v2"
    assert payload["latest"] == "spec-v3"
    assert "superseded too" in payload["notice"]
    assert "Prefer the successor" not in payload["notice"]
    keys = list(payload)
    assert keys.index("latest") < keys.index("content")


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_outline_passes_doc_type_and_size(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v2/outline").mock(
        return_value=httpx.Response(200, json=md(doc_type="specification", estimated_tokens=1484))
    )
    payload = await call_tool(make_mcp(discovery), "ics_asset_outline", {"slug_or_id": "spec-v2"})
    assert payload["doc_type"] == "specification"
    assert payload["estimated_tokens"] == 1484


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_outline_notice_points_at_latest(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v1/outline").mock(
        return_value=httpx.Response(
            200, json=md(freshness="superseded", superseded_by=SUCCESSOR, latest="spec-v3")
        )
    )
    payload = await call_tool(make_mcp(discovery), "ics_asset_outline", {"slug_or_id": "spec-v1"})
    assert payload["latest"] == "spec-v3"
    assert "`spec-v3`" in payload["notice"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_current_read_has_no_notice(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v2/file-mcp").mock(
        return_value=httpx.Response(
            200,
            json={
                "slug": "spec-v2",
                "path": "doc.md",
                "content": "# Spec v2\n",
                "freshness": "current",
                "superseded_by": None,
            },
        )
    )
    mcp = make_mcp(read)
    payload = await call_tool(mcp, "ics_asset_read", {"slug_or_id": "spec-v2"})
    # Empty fields are left out, and the result still matches the output schema.
    assert payload == {
        "slug": "spec-v2",
        "path": "doc.md",
        "freshness": "current",
        "content": "# Spec v2\n",
    }
    tool = next(t for t in await mcp.list_tools() if t.name == "ics_asset_read")
    jsonschema.validate(payload, tool.output_schema)


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_outline_without_edges_renders_cleanly(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/design/outline").mock(
        return_value=httpx.Response(200, json=outline())
    )
    payload = await call_tool(make_mcp(discovery), "ics_asset_outline", {"slug_or_id": "design"})

    assert payload["items"] == [{"title": "Scope", "level": 1}]
    assert payload["summary"] == "Booking API, first draft."
    assert payload["freshness"] == "current"
    assert "edges" not in payload
    assert "notice" not in payload


EDGES = {
    "nodes": {"architecture": {"title": "Architecture"}, "goals": {"title": "Goals"}},
    "edges": [
        [
            "spec-v1",
            "depends_on",
            "architecture",
            {"target_anchor": "data-layer", "changed": [1, 2]},
        ],
        ["spec-v1", "derived_from", "goals"],
    ],
}


def headings(n: int, *, deep: bool = True) -> list[dict[str, Any]]:
    out = []
    for i in range(n):
        level = 1 + (i % 3 if deep else 0)
        out.append(
            {
                "level": level,
                "text": f"Section {i}",
                "line": 10 * i + 1,
                "anchor": f"s{i}",
                "end_line": 10 * i + 9,
            }
        )
    return out


def md(**extra: Any) -> dict[str, Any]:
    base = outline(kind="md_single", line_count=500, headings=headings(3))
    base.pop("items")
    return {**base, **extra}


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_outline_edges_on_request_in_compact_shape(real_client, respx_mock, make_mcp):
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v1/outline").mock(
        return_value=httpx.Response(
            200, json=md(freshness="superseded", superseded_by=SUCCESSOR, **EDGES)
        )
    )
    mcp = make_mcp(discovery)
    bare = await call_tool(mcp, "ics_asset_outline", {"slug_or_id": "spec-v1"})
    assert "edges" not in bare and "nodes" not in bare
    assert "spec-v2" in bare["notice"]
    assert route.calls.last.request.url.params["shape"] == "compact"

    assert bare["superseded_by"] == "spec-v2"
    full = await call_tool(mcp, "ics_asset_outline", {"slug_or_id": "spec-v1", "edges": True})
    assert full["edges"] == EDGES["edges"]
    assert full["nodes"]["architecture"] == {"title": "Architecture"}
    # Edges are fetched only on request; the outline without them is cached.
    assert [c.request.url.params["edges"] for c in route.calls] == ["false", "true"]
    await call_tool(mcp, "ics_asset_outline", {"slug_or_id": "spec-v1"})
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_outline_max_level_keeps_shallow_headings(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/doc/outline").mock(
        return_value=httpx.Response(200, json=md(headings=headings(6)))
    )
    payload = await call_tool(
        make_mcp(discovery), "ics_asset_outline", {"slug_or_id": "doc", "max_level": 2}
    )
    assert {h["level"] for h in payload["headings"]} == {1, 2}
    assert all("end_line" in h for h in payload["headings"])
    assert "trimmed" not in payload


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_long_outline_is_trimmed_by_level_never_stubbed(real_client, respx_mock, make_mcp):
    big = md(freshness="superseded", superseded_by=SUCCESSOR, headings=headings(240), **EDGES)
    assert len(json.dumps(big)) > get_settings().mcp_response_max_chars
    respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v1/outline").mock(
        return_value=httpx.Response(200, json=big)
    )
    payload = await call_tool(
        make_mcp(discovery), "ics_asset_outline", {"slug_or_id": "spec-v1", "edges": True}
    )
    assert payload["freshness"] == "superseded"
    assert "spec-v2" in payload["notice"]
    assert payload["trimmed"]["edges"] == "bare"
    assert payload["edges"] == [e[:3] for e in EDGES["edges"]]
    level = payload["trimmed"]["max_level"]
    assert payload["headings"] and {h["level"] for h in payload["headings"]} <= set(
        range(1, level + 1)
    )
    assert "anchor=" in payload["hint"] and "ics_asset_outline" not in payload["hint"]
    assert len(json.dumps(payload)) <= get_settings().mcp_response_max_chars


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_flat_outline_pages_with_offset(real_client, respx_mock, make_mcp):
    big = md(headings=headings(400, deep=False))
    respx_mock.get(f"{ICS}/api/assets/by-slug/doc/outline").mock(
        return_value=httpx.Response(200, json=big)
    )
    mcp = make_mcp(discovery)
    first = await call_tool(mcp, "ics_asset_outline", {"slug_or_id": "doc"})
    nxt = first["trimmed"]["next_offset"]
    assert first["headings"][0]["anchor"] == "s0" and len(first["headings"]) == nxt
    assert f"offset={nxt}" in first["hint"]
    second = await call_tool(mcp, "ics_asset_outline", {"slug_or_id": "doc", "offset": nxt})
    assert second["headings"][0]["anchor"] == f"s{nxt}"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_read_by_anchor_reads_the_section(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v2/outline").mock(
        return_value=httpx.Response(200, json=md())
    )
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v2/file-mcp").mock(
        return_value=httpx.Response(200, json={"slug": "spec-v2", "path": "doc.md", "content": "x"})
    )
    mcp = make_mcp(read)
    await call_tool(mcp, "ics_asset_read", {"slug_or_id": "spec-v2", "anchor": "s1"})
    assert route.calls.last.request.url.params["lines"] == "11-19"
    # An edge target reference works as `slug_or_id`.
    await call_tool(mcp, "ics_asset_read", {"slug_or_id": "ics://asset/spec-v2#s2"})
    assert route.calls.last.request.url.params["lines"] == "21-29"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_read_by_unknown_anchor_lists_known_ones(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v2/outline").mock(
        return_value=httpx.Response(200, json=md())
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            make_mcp(read), "ics_asset_read", {"slug_or_id": "spec-v2", "anchor": "nope"}
        )
    err = json.loads(str(exc.value))
    assert err["code"] == "anchor_not_found"
    assert "s0" in err["hint"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_read_by_anchor_while_outline_builds(real_client, respx_mock, make_mcp):
    respx_mock.get(f"{ICS}/api/assets/by-slug/spec-v2/outline").mock(
        return_value=httpx.Response(202, json={"status": "building", "retry_after": 2})
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(make_mcp(read), "ics_asset_read", {"slug_or_id": "spec-v2", "anchor": "s1"})
    assert json.loads(str(exc.value))["code"] == "outline_building"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_building_outline_points_to_a_direct_read(real_client, respx_mock, make_mcp):
    """A `building` outline tells the agent it can read the file now, and is
    not cached, so the next call sees the finished outline."""
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/outline").mock(
        side_effect=[
            httpx.Response(200, json={"status": "building", "retry_after": 2}),
            httpx.Response(200, json=outline()),
        ]
    )
    mcp = make_mcp(discovery)
    first = await call_tool(mcp, "ics_asset_outline", {"slug_or_id": "abc"})
    assert first["status"] == "building"
    assert "ics_asset_read" in first["hint"]
    second = await call_tool(mcp, "ics_asset_outline", {"slug_or_id": "abc"})
    assert second["summary"] == "Booking API, first draft."
    assert route.call_count == 2


def _collection(files: list[dict[str, Any]]) -> dict[str, Any]:
    return {"slug": "vault", "kind": "md_collection", "version": 1, "files": files}


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_collection_with_one_oversized_file_still_moves_forward(
    real_client, respx_mock, make_mcp
):
    """150 H1 headings in one file: no level cut helps and the file alone is
    over the limit, so the page shows part of its headings and moves past it
    instead of an empty page that offers the same offset again."""
    big = {"path": "big.md", "headings": headings(150, deep=False)}
    small = {"path": "small.md", "headings": headings(2, deep=False)}
    respx_mock.get(f"{ICS}/api/assets/by-slug/vault/outline").mock(
        return_value=httpx.Response(200, json=_collection([big, small]))
    )
    cap = 6000
    monkey = pytest.MonkeyPatch()
    monkey.setattr(get_settings(), "mcp_response_max_chars", cap)
    try:
        mcp = make_mcp(discovery)
        first = await call_tool(mcp, "ics_asset_outline", {"slug_or_id": "vault"})
        second = await call_tool(
            mcp,
            "ics_asset_outline",
            {"slug_or_id": "vault", "offset": first["trimmed"]["next_offset"]},
        )
    finally:
        monkey.undo()

    assert [f["path"] for f in first["files"]] == ["big.md"]
    shown = len(first["files"][0]["headings"])
    assert 0 < shown < 150
    assert first["trimmed"]["file_headings"] == {"path": "big.md", "shown": shown, "total": 150}
    assert "path='big.md'" in first["hint"]
    assert first["trimmed"]["next_offset"] == 1
    assert payload_chars(first) <= cap
    assert [f["path"] for f in second["files"]] == ["small.md"]
    assert "trimmed" not in second
