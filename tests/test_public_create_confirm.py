"""Creating an asset with `share_mode="public"` publishes it to anyone with
the URL, so it goes through the same gate as `ics_share_create_link(mode=
"public")`. Calls go through a real MCP client, which validates
`structuredContent` against the tool's output schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult

from ics_mcp.tools import session as session_tool
from ics_mcp.tools import write_documents, write_html, write_md
from tests.conftest import ICS, create_md_response

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _create_calls(pdf: Path) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("ics_asset_create_md", {"title": "T", "content": "x"}),
        (
            "ics_asset_create_collection",
            {"title": "V", "files": [{"path": "a.md", "content": "a"}]},
        ),
        (
            "ics_asset_create_html",
            {
                "title": "H",
                "entry_path": "index.html",
                "files": [{"path": "index.html", "content_text": "<p>x</p>"}],
            },
        ),
        ("ics_asset_create_document", {"file_path": str(pdf)}),
    ]


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    p = tmp_path / "report.pdf"
    p.write_bytes(PDF_BYTES)
    return p


@pytest.fixture
def mcp(make_mcp):
    return make_mcp(write_md, write_html, write_documents, session_tool)


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(4))
@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_public_create_dry_run_previews_without_calling_ics(
    real_client, respx_mock, mcp, pdf_file, index
):
    tool, payload = _create_calls(pdf_file)[index]
    async with Client(mcp) as client:
        await client.call_tool("ics_session_set_mode", {"mode": "dry_run"})
        result = await client.call_tool(tool, {"payload": {**payload, "share_mode": "public"}})
    assert result.structured_content is not None
    assert result.structured_content["action"] == "create_public_link"
    assert "dry_run" in result.structured_content["note"]
    assert respx_mock.calls.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(4))
@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_public_create_without_elicitation_requires_confirmation(
    real_client, respx_mock, mcp, pdf_file, index
):
    tool, payload = _create_calls(pdf_file)[index]
    async with Client(mcp) as client:
        result = await client.call_tool(
            tool, {"payload": {**payload, "share_mode": "public"}}, raise_on_error=False
        )
    assert result.is_error
    assert "confirm_required" in result.content[0].text  # type: ignore[union-attr]
    assert respx_mock.calls.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["yolo", "dry_run"])
@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_public_create_explicit_refusal_wins_over_mode(real_client, respx_mock, mcp, mode):
    async with Client(mcp) as client:
        await client.call_tool("ics_session_set_mode", {"mode": mode})
        result = await client.call_tool(
            "ics_asset_create_md",
            {"payload": {"title": "T", "content": "x", "share_mode": "public"}, "confirm": False},
            raise_on_error=False,
        )
    assert result.is_error
    assert "confirm_required" in result.content[0].text  # type: ignore[union-attr]
    assert respx_mock.calls.call_count == 0


def _mock_create_md(respx_mock) -> respx.Route:
    return respx_mock.post(f"{ICS}/api/assets").mock(
        return_value=httpx.Response(201, json=create_md_response())
    )


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_public_create_runs_in_yolo_mode(real_client, respx_mock, mcp):
    route = _mock_create_md(respx_mock)
    async with Client(mcp) as client:
        await client.call_tool("ics_session_set_mode", {"mode": "yolo"})
        result = await client.call_tool(
            "ics_asset_create_md",
            {"payload": {"title": "T", "content": "x", "share_mode": "public"}},
        )
    assert route.call_count == 1
    assert route.calls[0].request.url.params["share_mode"] == "public"
    # The result is not wrapped in {"result": ...} by the custom output schema.
    assert result.structured_content is not None
    assert result.structured_content["slug"] == "abc"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_public_create_interactive_accept_creates(real_client, respx_mock, mcp):
    route = _mock_create_md(respx_mock)
    prompts: list[str] = []

    async def accept(message, response_type, params, context):
        prompts.append(message)
        return {"confirm": True}

    async with Client(mcp, elicitation_handler=accept) as client:
        result = await client.call_tool(
            "ics_asset_create_md",
            {"payload": {"title": "T", "content": "x", "share_mode": "public"}},
        )
    assert route.call_count == 1
    assert result.structured_content is not None
    assert result.structured_content["slug"] == "abc"
    assert len(prompts) == 1
    assert "create_public_link" in prompts[0]
    assert "'T'" in prompts[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer", [ElicitResult(action="decline"), {"confirm": False}], ids=["decline", "unchecked"]
)
@respx.mock(assert_all_mocked=True, assert_all_called=False)
async def test_public_create_interactive_decline_creates_nothing(
    real_client, respx_mock, mcp, answer
):
    async def respond(message, response_type, params, context):
        return answer

    async with Client(mcp, elicitation_handler=respond) as client:
        result = await client.call_tool(
            "ics_asset_create_md",
            {"payload": {"title": "T", "content": "x", "share_mode": "public"}},
            raise_on_error=False,
        )
    assert result.is_error
    assert "confirm_declined" in result.content[0].text  # type: ignore[union-attr]
    assert respx_mock.calls.call_count == 0


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_org_create_does_not_ask(real_client, respx_mock, mcp):
    route = _mock_create_md(respx_mock)

    async def fail(message, response_type, params, context):
        raise AssertionError("an org_sso create must not ask")

    async with Client(mcp, elicitation_handler=fail) as client:
        await client.call_tool(
            "ics_asset_create_md",
            {"payload": {"title": "T", "content": "x", "share_mode": "org_sso"}},
        )
    assert route.call_count == 1
