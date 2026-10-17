"""Tests that catch protocol-level regressions in the MCP server bootstrap.

- All declared tools must have full spec annotations
  (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`).
- Destructive tools must declare `destructiveHint=True`.
- Discovery tools must declare `readOnlyHint=True`.
- Resource templates must follow RFC 6570.
"""

from __future__ import annotations

import re

import pytest


@pytest.mark.asyncio
async def test_server_registers_expected_components():
    from ics_mcp.server import mcp

    tools = await mcp._list_tools()
    names = {t.name for t in tools}
    # A sample of tools that must exist
    required = {
        "ics_help",
        "ics_whoami",
        "ics_session_set_mode",
        "ics_session_status",
        "ics_assets_list",
        "ics_assets_search",
        "ics_asset_meta",
        "ics_asset_list_files",
        "ics_asset_outline",
        "ics_asset_read",
        "ics_asset_create_md",
        "ics_asset_create_collection",
        "ics_asset_create_html",
        "ics_asset_create_document",
        "ics_asset_replace_document",
        "ics_asset_update_content",
        "ics_asset_delete",
        "ics_asset_undelete",
        "ics_asset_pin",
        "ics_asset_set_tags",
        "ics_asset_html_replace_bundle",
        "ics_asset_html_security_review",
        "ics_share_create_link",
        "ics_share_revoke",
        "ics_share_grant_user",
        "ics_asset_new_version",
        "ics_asset_restore_version",
    }
    missing = required - names
    assert not missing, f"Missing tools: {missing}"


@pytest.mark.asyncio
async def test_all_tools_have_complete_annotations():
    from ics_mcp.server import mcp

    tools = await mcp._list_tools()
    for t in tools:
        ann = t.annotations
        assert ann is not None, f"{t.name}: missing annotations"
        for key in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            value = getattr(ann, key, None)
            assert value is not None, f"{t.name}: missing annotation {key}"
            assert isinstance(value, bool), f"{t.name}: {key} not bool"


@pytest.mark.asyncio
async def test_destructive_tools_flagged():
    from ics_mcp.server import mcp

    tools = await mcp._list_tools()
    by_name = {t.name: t for t in tools}
    destructive_expected = {
        "ics_asset_delete",
        "ics_asset_delete_file",
        "ics_asset_update_content",
        "ics_asset_html_replace_bundle",
        "ics_asset_replace_document",
        "ics_asset_restore_version",
        "ics_share_revoke",
        "ics_asset_move_file",
        "ics_relation_remove",
        "ics_task_unlink",
        "ics_project_links_set",
    }
    for name in destructive_expected:
        assert name in by_name, name
        assert by_name[name].annotations.destructiveHint is True, name


@pytest.mark.asyncio
async def test_destructive_tools_expose_confirm_in_input_schema():
    """Docs promise a per-call `confirm` override, but FastMCP
    builds `inputSchema` with `additionalProperties: false` from the
    signature, so every destructive (guarded) tool must declare the param
    or the override is unsendable."""
    from ics_mcp.server import mcp

    tools = await mcp._list_tools()
    for t in tools:
        if not (t.annotations and t.annotations.destructiveHint):
            continue
        props = t.parameters.get("properties", {})
        assert "confirm" in props, f"{t.name}: missing `confirm` in inputSchema"
        types = {s.get("type") for s in props["confirm"].get("anyOf", [])}
        assert types == {"boolean", "null"}, f"{t.name}: confirm must be bool|null"
        # `.get(...) is None` would also pass when the default key is missing,
        # and a missing default combined with required makes confirm mandatory,
        # which is exactly the regression of this contract. Check both explicitly.
        assert "default" in props["confirm"], f"{t.name}: confirm has no default"
        assert props["confirm"]["default"] is None, f"{t.name}: confirm default not null"
        required = t.parameters.get("required", [])
        assert "confirm" not in required, f"{t.name}: confirm must stay optional"


@pytest.mark.asyncio
async def test_readonly_tools_flagged():
    from ics_mcp.server import mcp

    tools = await mcp._list_tools()
    by_name = {t.name: t for t in tools}
    ro_expected = {
        "ics_whoami",
        "ics_assets_list",
        "ics_assets_search",
        "ics_asset_meta",
        "ics_asset_list_files",
        "ics_asset_outline",
        "ics_asset_read",
        "ics_asset_read_rendered",
        "ics_asset_versions",
        "ics_asset_diff",
        "ics_asset_html_security_review",
        "ics_projects_list",
        "ics_shares_list",
        "ics_help",
        "ics_session_status",
        "ics_project_links",
        "ics_asset_relations",
        "ics_graph_neighbourhood",
        "ics_task_context",
        "ics_asset_external_refs",
    }
    for name in ro_expected:
        assert name in by_name, name
        assert by_name[name].annotations.readOnlyHint is True, name


@pytest.mark.asyncio
async def test_resource_templates_follow_rfc6570():
    from ics_mcp.server import mcp

    templates = await mcp._list_resource_templates()
    expected_uris = {
        "ics://asset/{slug}",
        "ics://asset/{slug}/outline",
        "ics://asset/{slug}/file/{path}",
        "ics://asset/{slug}@v{version}",
        "ics://asset/{slug}@v{version}/file/{path}",
        "ics://project/{slug}",
    }
    actual = {
        getattr(t, "uriTemplate", None) or getattr(t, "uri_template", None) for t in templates
    }
    assert expected_uris <= actual, f"missing: {expected_uris - actual}"
    # Light RFC 6570 sanity: placeholders are `{name}`.
    for uri in actual:
        for token in re.findall(r"\{([^}]+)\}", uri):
            assert token.isidentifier() or token.startswith("+"), uri


@pytest.mark.asyncio
async def test_prompts_registered():
    from ics_mcp.server import mcp

    prompts = await mcp._list_prompts()
    names = {p.name for p in prompts}
    assert names == {"share_with_team", "summarize_collection", "migrate_to_collection"}
