"""Document metadata (ICS ADR-0015): `ics_asset_set_meta`, `ics_doc_types`
and the ICS metadata error codes. Response mocks follow the ICS contract
(`routes/assets/metadata.py`, `routes/doc_types.py`)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from ics_mcp.config import get_settings
from ics_mcp.tools import metadata
from tests.conftest import ASSET_ID, ICS, call_tool, mock_resolve

USER_ID = "22222222-2222-2222-2222-222222222222"
OTHER_ID = "33333333-3333-3333-3333-333333333333"


def meta_detail(**overrides: Any) -> dict[str, Any]:
    """Shape of `asset_metadata.metadata_detail` returned by the metadata writes."""
    base: dict[str, Any] = {
        "id": ASSET_ID,
        "version": 1,
        "summary": "What the doc is for.",
        "summary_source": "agent",
        "doc_type": "specification",
        "freshness": "current",
        "flags": [],
        "maintainer": None,
        "summary_version": 1,
        "maintainer_id": None,
        "review_due_at": None,
        "reviewed_at": None,
        "reviewed_by": None,
        "language": None,
        "properties": {},
    }
    base.update(overrides)
    return base


def _error_payload(exc: pytest.ExceptionInfo[ToolError]) -> dict[str, Any]:
    return json.loads(str(exc.value))


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_set_meta_sends_only_given_fields(real_client, respx_mock, make_mcp):
    mcp = make_mcp(metadata)
    mock_resolve(respx_mock)
    patch = respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}/meta").mock(
        return_value=httpx.Response(200, json=meta_detail())
    )
    payload = await call_tool(
        mcp,
        "ics_asset_set_meta",
        {"slug_or_id": "abc", "summary": "What the doc is for.", "doc_type": "specification"},
    )
    assert json.loads(patch.calls[0].request.content) == {
        "summary": "What the doc is for.",
        "doc_type": "specification",
    }
    assert payload["doc_type"] == "specification"
    assert payload["summary"] == "What the doc is for."
    assert payload["summary_source"] == "agent"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_set_meta_empty_string_clears_field(real_client, respx_mock, make_mcp):
    mcp = make_mcp(metadata)
    mock_resolve(respx_mock)
    patch = respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}/meta").mock(
        return_value=httpx.Response(200, json=meta_detail(doc_type=None))
    )
    await call_tool(
        mcp, "ics_asset_set_meta", {"slug_or_id": "abc", "doc_type": "", "maintainer_email": ""}
    )
    assert json.loads(patch.calls[0].request.content) == {
        "doc_type": None,
        "maintainer_id": None,
    }


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_set_meta_resolves_maintainer_email(real_client, respx_mock, make_mcp):
    mcp = make_mcp(metadata)
    mock_resolve(respx_mock)
    respx_mock.get(f"{ICS}/api/auth/oauth/me").mock(
        return_value=httpx.Response(200, json={"user_id": USER_ID, "email": "me@example.com"})
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/shares").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "s1", "user_id": OTHER_ID, "email": "ann@example.com", "role": "editor"}],
        )
    )
    patch = respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}/meta").mock(
        return_value=httpx.Response(200, json=meta_detail(maintainer_id=OTHER_ID))
    )
    await call_tool(
        mcp, "ics_asset_set_meta", {"slug_or_id": "abc", "maintainer_email": "Ann@Example.com"}
    )
    assert json.loads(patch.calls[0].request.content) == {"maintainer_id": OTHER_ID}


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_set_meta_unknown_maintainer_fails_before_patch(real_client, respx_mock, make_mcp):
    mcp = make_mcp(metadata)
    mock_resolve(respx_mock)
    respx_mock.get(f"{ICS}/api/auth/oauth/me").mock(
        return_value=httpx.Response(200, json={"user_id": USER_ID, "email": "me@example.com"})
    )
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/shares").mock(
        return_value=httpx.Response(200, json=[])
    )
    patch = respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}/meta")
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp, "ics_asset_set_meta", {"slug_or_id": "abc", "maintainer_email": "x@example.com"}
        )
    err = _error_payload(exc)
    assert err["code"] == "maintainer_unknown"
    assert err["field"] == "maintainer_email"
    assert not patch.called


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_set_meta_without_fields_is_rejected(real_client, respx_mock, make_mcp):
    mcp = make_mcp(metadata)
    mock_resolve(respx_mock)
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_set_meta", {"slug_or_id": "abc"})
    assert _error_payload(exc)["code"] == "invalid_argument"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_set_meta_doc_type_unknown(real_client, respx_mock, make_mcp):
    mcp = make_mcp(metadata)
    mock_resolve(respx_mock)
    respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}/meta").mock(
        return_value=httpx.Response(
            400,
            json={"detail": "unknown document type: memo", "code": "doc_type_unknown"},
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_set_meta", {"slug_or_id": "abc", "doc_type": "memo"})
    err = _error_payload(exc)
    assert err["code"] == "doc_type_unknown"
    assert err["status"] == 400
    assert "ics_doc_types" in err["hint"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_set_meta_metadata_invalid_surfaces_field(real_client, respx_mock, make_mcp):
    mcp = make_mcp(metadata)
    mock_resolve(respx_mock)
    respx_mock.patch(f"{ICS}/api/assets/{ASSET_ID}/meta").mock(
        return_value=httpx.Response(
            400,
            json={
                "detail": "language: expected a language tag such as 'pl' or 'en-GB'",
                "code": "metadata_invalid",
                "field": "language",
            },
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, "ics_asset_set_meta", {"slug_or_id": "abc", "language": "polish"})
    err = _error_payload(exc)
    assert err["code"] == "metadata_invalid"
    assert err["field"] == "language"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_doc_types_returns_agent_fields(real_client, respx_mock, make_mcp):
    mcp = make_mcp(metadata)
    respx_mock.get(f"{ICS}/api/doc-types").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "key": "specification",
                    "label": "Specification",
                    "label_pl": "Specyfikacja",
                    "label_en": "Specification",
                    "agent_hint": "What a system must do.",
                    "default_review_days": 180,
                    "properties_schema": {},
                    "position": 0,
                    "archived": False,
                }
            ],
        )
    )
    payload = await call_tool(mcp, "ics_doc_types", {})
    assert payload == {
        "doc_types": [
            {
                "key": "specification",
                "label": "Specification",
                "agent_hint": "What a system must do.",
                "default_review_days": 180,
            }
        ]
    }


# ----------------- metadata in listings, search, create and versions -----------------


def index_item(slug: str, **overrides: Any) -> dict[str, Any]:
    """Shape of an ICS `AssetIndexItem` with the ADR-0015 metadata block."""
    base: dict[str, Any] = {
        "id": ASSET_ID,
        "slug": slug,
        "title": "T",
        "kind": "md_single",
        "size_bytes": 100,
        "version": 2,
        "updated_at": "2026-09-20T08:00:00Z",
        "content_updated_at": "2026-09-19T08:00:00Z",
        "content_updated_by": USER_ID,
        "pinned": False,
        "owner_id": USER_ID,
        "project_id": None,
        "tags": ["q3"],
        "has_versions": True,
        "access_role": "owner_file",
        "shared_in": False,
        "summary": "Preview of the summary",
        "summary_source": "human",
        "doc_type": "specification",
        "freshness": "current",
        "flags": [],
        "maintainer": {"id": USER_ID, "email": "me@example.com", "display_name": "Me"},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_list_passes_metadata_filters(real_client, respx_mock, make_mcp):
    from ics_mcp.tools import discovery

    mcp = make_mcp(discovery)
    route = respx_mock.get(f"{ICS}/api/assets/index").mock(
        return_value=httpx.Response(200, json={"items": [], "next_cursor": None})
    )
    await call_tool(
        mcp,
        "ics_assets_list",
        {
            "doc_type": ["specification", "decision"],
            "freshness": ["review_overdue", "superseded"],
            "updated_since": "2026-09-01T00:00:00Z",
            "touched_since": "2026-09-10T00:00:00Z",
        },
    )
    params = route.calls[0].request.url.params
    assert params.get_list("doc_type") == ["specification", "decision"]
    assert params.get_list("freshness") == ["review_overdue", "superseded"]
    assert params["updated_since"].startswith("2026-09-01T00:00:00")
    assert params["touched_since"].startswith("2026-09-10T00:00:00")


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_list_items_carry_metadata(real_client, respx_mock, make_mcp):
    from ics_mcp.tools import discovery

    mcp = make_mcp(discovery)
    items = [
        index_item("a"),
        index_item("b", freshness="review_overdue", flags=["summary_stale"], maintainer=None),
        index_item("c", freshness="superseded", summary=None, summary_source=None, doc_type=None),
    ]
    respx_mock.get(f"{ICS}/api/assets/index").mock(
        return_value=httpx.Response(200, json={"items": items, "next_cursor": None})
    )
    payload = await call_tool(mcp, "ics_assets_list", {})
    got = payload["items"]
    assert [it["freshness"] for it in got] == ["current", "review_overdue", "superseded"]
    assert all("freshness" in it and it["freshness"] for it in got)
    # One timestamp, the day of the last content change.
    assert got[0]["updated_at"] == "2026-09-19"
    assert got[0]["tags"] == ["q3"]
    assert got[1]["flags"] == ["summary_stale"]
    assert "doc_type" not in got[2]
    for dropped in (
        "id",
        "owner_id",
        "has_versions",
        "summary_source",
        "content_updated_at",
        "kind",
        "size_bytes",
        "version",
        "access_role",
        "maintainer",
        "pinned",
    ):
        assert dropped not in got[0], dropped


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_list_detail_full_returns_the_whole_row(real_client, respx_mock, make_mcp):
    from ics_mcp.tools import discovery

    long_summary = "word " * 60
    respx_mock.get(f"{ICS}/api/assets/index").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [index_item("a", kind="html_bundle", summary=long_summary)],
                "next_cursor": None,
            },
        )
    )
    mcp = make_mcp(discovery)
    compact = (await call_tool(mcp, "ics_assets_list", {}))["items"][0]
    assert compact["kind"] == "html_bundle"
    assert len(compact["summary"]) <= 120 and compact["summary"].endswith("\u2026")
    full = (await call_tool(mcp, "ics_assets_list", {"detail": "full"}))["items"][0]
    assert full["summary"] == long_summary
    assert full["maintainer"]["display_name"] == "Me"
    assert full["id"] == ASSET_ID
    for field in ("size_bytes", "version", "access_role", "owner_id", "content_updated_at"):
        assert field in full, field


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_list_items_are_slim(real_client, respx_mock, make_mcp):
    """Compact items leave out the project id; `superseded_by` becomes the
    successor slug, `latest` and `estimated_tokens` pass through when ICS
    sends them, and a row without them still validates."""
    from ics_mcp.tools import discovery

    mcp = make_mcp(discovery)
    project = "0c1e9d70-97dd-4d77-8673-f67fbd73f918"
    successor = {"id": USER_ID, "slug": "spec-v2", "title": "Spec v2"}
    items = [
        index_item(
            "a",
            project_id=project,
            freshness="superseded",
            superseded_by=successor,
            latest="spec-v3",
            estimated_tokens=820,
        ),
        index_item("b", project_id=project),
    ]
    route = respx_mock.get(f"{ICS}/api/assets/index").mock(
        return_value=httpx.Response(200, json={"items": items, "next_cursor": "c2"})
    )
    payload = await call_tool(mcp, "ics_assets_list", {"project_id": project})
    assert route.calls[0].request.url.params["limit"] == "20"
    first, second = payload["items"]
    assert first["superseded_by"] == "spec-v2"
    assert first["latest"] == "spec-v3"
    assert first["estimated_tokens"] == 820
    assert "project_id" not in first
    assert not {"superseded_by", "latest", "estimated_tokens"} & set(second)
    assert payload["next_cursor"] == "c2"
    full = await call_tool(mcp, "ics_assets_list", {"detail": "full"})
    assert full["items"][0]["project_id"] == project


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_list_page_is_cut_to_the_response_limit(
    real_client, respx_mock, make_mcp, monkeypatch
):
    """A page over the limit keeps the first items and gets a cursor for
    exactly those, from a second request with the smaller limit."""
    from ics_mcp.tools import discovery

    monkeypatch.setattr(get_settings(), "mcp_response_max_chars", 1500)
    mcp = make_mcp(discovery)
    items = [index_item(f"doc-{i}", summary="x" * 300) for i in range(8)]

    def page(request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params["limit"])
        return httpx.Response(200, json={"items": items[:limit], "next_cursor": f"after-{limit}"})

    route = respx_mock.get(f"{ICS}/api/assets/index").mock(side_effect=page)
    payload = await call_tool(mcp, "ics_assets_list", {"limit": 8})
    assert payload["truncated"] is True
    assert 1 <= payload["count"] < 8
    assert payload["next_cursor"] == f"after-{payload['count']}"
    assert route.calls[1].request.url.params["limit"] == str(payload["count"])


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_meta_returns_full_metadata(real_client, respx_mock, make_mcp):
    from ics_mcp.tools import discovery

    mcp = make_mcp(discovery)
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").mock(
        return_value=httpx.Response(200, json=index_item("abc", summary="Full summary."))
    )
    payload = await call_tool(mcp, "ics_asset_meta", {"slug_or_id": "abc"})
    assert payload["summary"] == "Full summary."
    assert payload["summary_source"] == "human"
    assert payload["freshness"] == "current"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_meta_names_the_end_of_the_supersedes_chain(real_client, respx_mock, make_mcp):
    from ics_mcp.tools import discovery

    successor = {"id": USER_ID, "slug": "spec-v2", "title": "Spec v2"}
    respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").mock(
        return_value=httpx.Response(
            200,
            json=index_item(
                "abc", freshness="superseded", superseded_by=successor, latest="spec-v3"
            ),
        )
    )
    payload = await call_tool(make_mcp(discovery), "ics_asset_meta", {"slug_or_id": "abc"})
    assert payload["superseded_by"] == "spec-v2"
    assert payload["latest"] == "spec-v3"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_search_passes_metadata_filters(real_client, respx_mock, make_mcp):
    from ics_mcp.tools import discovery

    mcp = make_mcp(discovery)
    route = respx_mock.get(f"{ICS}/api/assets/search-mcp").mock(
        return_value=httpx.Response(
            200, json={"items": [], "total": 0, "offset": 0, "limit": 20, "has_more": False}
        )
    )
    await call_tool(
        mcp,
        "ics_assets_search",
        {"q": "okr", "doc_type": ["report"], "tag": ["q3", "okr"], "freshness": ["current"]},
    )
    params = route.calls[0].request.url.params
    assert params.get_list("doc_type") == ["report"]
    assert params.get_list("tag") == ["q3", "okr"]
    assert params.get_list("freshness") == ["current"]


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_md_sends_doc_type_and_summary(real_client, respx_mock, make_mcp):
    from ics_mcp.tools import write_md
    from tests.conftest import create_md_response

    mcp = make_mcp(write_md)
    route = respx_mock.post(f"{ICS}/api/assets").mock(
        return_value=httpx.Response(201, json=create_md_response())
    )
    await call_tool(
        mcp,
        "ics_asset_create_md",
        {
            "payload": {
                "title": "T",
                "content": "# T\n",
                "doc_type": "specification",
                "summary": "Spec of X.",
            }
        },
    )
    body = route.calls[0].request.content
    assert b'name="doc_type"\r\n\r\nspecification' in body
    assert b'name="summary"\r\n\r\nSpec of X.' in body


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_html_doc_type_unknown_is_promoted(real_client, respx_mock, make_mcp):
    from ics_mcp.tools import write_html

    mcp = make_mcp(write_html)
    route = respx_mock.post(f"{ICS}/api/assets/html-json").mock(
        return_value=httpx.Response(
            400, json={"detail": "unknown document type: memo", "code": "doc_type_unknown"}
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_create_html",
            {
                "payload": {
                    "title": "Dash",
                    "entry_path": "index.html",
                    "files": [{"path": "index.html", "content_text": "<p>x</p>"}],
                    "doc_type": "memo",
                }
            },
        )
    assert json.loads(route.calls[0].request.content)["doc_type"] == "memo"
    assert _error_payload(exc)["code"] == "doc_type_unknown"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_new_version_sends_change_note(real_client, respx_mock, make_mcp):
    from ics_mcp.tools import write_versions

    mcp = make_mcp(write_versions)
    mock_resolve(respx_mock)
    route = respx_mock.post(f"{ICS}/api/assets/{ASSET_ID}/versions").mock(
        return_value=httpx.Response(201, json={"id": ASSET_ID, "version": 2})
    )
    await call_tool(
        mcp,
        "ics_asset_new_version",
        {
            "slug_or_id": "abc",
            "files": [{"path": "a.md", "content": "# A\n"}],
            "change_note": "Updated the budget table.",
            "confirm": True,
        },
    )
    assert b'name="change_note"\r\n\r\nUpdated the budget table.' in route.calls[0].request.content


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_create_pdf_metadata_invalid_is_promoted(real_client, respx_mock, make_mcp, tmp_path):
    from ics_mcp.tools import write_documents

    pdf = tmp_path / "spec.pdf"
    pdf.write_bytes(b"%PDF-1.7\n%%EOF\n")
    mcp = make_mcp(write_documents)
    route = respx_mock.post(f"{ICS}/api/assets/pdf").mock(
        return_value=httpx.Response(
            400,
            json={"detail": "summary: too long", "code": "metadata_invalid", "field": "summary"},
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(
            mcp,
            "ics_asset_create_document",
            {"payload": {"file_path": str(pdf), "summary": "x" * 50}},
        )
    assert b'name="summary"' in route.calls[0].request.content
    err = _error_payload(exc)
    assert (err["code"], err["field"]) == ("metadata_invalid", "summary")


@pytest.mark.parametrize(
    ("tool", "path", "args"),
    [
        ("ics_assets_list", "/api/assets/index", {}),
        ("ics_assets_search", "/api/assets/search-mcp", {"q": "spec"}),
    ],
)
@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_unknown_doc_type_filter_is_invalid_argument(
    real_client, respx_mock, make_mcp, tool, path, args
):
    from ics_mcp.tools import discovery

    mcp = make_mcp(discovery)
    respx_mock.get(f"{ICS}{path}").mock(
        return_value=httpx.Response(
            400,
            json={
                "detail": "unknown document type: memo",
                "code": "doc_type_filter_unknown",
                "field": "doc_type",
                "allowed": ["specification", "decision"],
            },
        )
    )
    with pytest.raises(ToolError) as exc:
        await call_tool(mcp, tool, {**args, "doc_type": ["memo"]})
    err = json.loads(str(exc.value))
    assert err["code"] == "invalid_argument"
    assert err["field"] == "doc_type"
    assert err["data"] == {"allowed": ["specification", "decision"]}
    assert "specification" in err["message"]
