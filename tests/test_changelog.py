"""Every tool added since the last release is listed under [Unreleased], so a
new tool cannot ship without a changelog entry.

`RELEASED_TOOLS` is the catalog of the last release (0.1.0); the
first changelog entries predate per-tool notes, so the released sections
cannot serve as that list. On a release, add the shipped tools here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ics_mcp.server import build_mcp
from tests.conftest import list_tools

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

RELEASED_TOOLS = frozenset(
    {
        "ics_asset_add_file",
        "ics_asset_create_collection",
        "ics_asset_create_document",
        "ics_asset_create_empty_file",
        "ics_asset_create_html",
        "ics_asset_create_md",
        "ics_asset_delete",
        "ics_asset_delete_file",
        "ics_asset_diff",
        "ics_asset_external_refs",
        "ics_asset_html_replace_bundle",
        "ics_asset_html_security_review",
        "ics_asset_list_files",
        "ics_asset_meta",
        "ics_asset_ocr",
        "ics_asset_move_file",
        "ics_asset_new_version",
        "ics_asset_outline",
        "ics_asset_pin",
        "ics_asset_read",
        "ics_asset_read_rendered",
        "ics_asset_relations",
        "ics_asset_rescan_relations",
        "ics_asset_rename",
        "ics_asset_replace_document",
        "ics_asset_restore_version",
        "ics_asset_set_meta",
        "ics_asset_set_tags",
        "ics_asset_undelete",
        "ics_asset_update_content",
        "ics_asset_versions",
        "ics_assets_list",
        "ics_assets_search",
        "ics_doc_types",
        "ics_graph_neighbourhood",
        "ics_help",
        "ics_project_links",
        "ics_project_links_set",
        "ics_projects_list",
        "ics_relation_add",
        "ics_relation_remove",
        "ics_relation_update",
        "ics_session_set_mode",
        "ics_session_status",
        "ics_share_create_link",
        "ics_share_grant_user",
        "ics_share_resolve",
        "ics_share_revoke",
        "ics_shares_list",
        "ics_task_context",
        "ics_task_link",
        "ics_task_unlink",
        "ics_whoami",
    }
)


def _unreleased() -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    match = re.search(r"^## \[Unreleased\]\n(.*?)^## \[", text, re.DOTALL | re.MULTILINE)
    assert match, "CHANGELOG needs an [Unreleased] section above the released ones"
    return match.group(1)


@pytest.mark.asyncio
async def test_unreleased_lists_every_new_tool(settings):
    tools = {t.name for t in await list_tools(build_mcp(settings))}
    unreleased = _unreleased()
    missing = {n for n in tools - RELEASED_TOOLS if not re.search(rf"`{n}`", unreleased)}
    assert missing == set()


@pytest.mark.asyncio
async def test_unreleased_notes_every_removed_tool(settings):
    """A released tool that disappeared is named under `### Removed`."""
    tools = {t.name for t in await list_tools(build_mcp(settings))}
    unreleased = _unreleased()
    removed_section = unreleased.split("### Removed", 1)[1] if "### Removed" in unreleased else ""
    removed_section = removed_section.split("\n### ", 1)[0]
    unnoted = {n for n in RELEASED_TOOLS - tools if f"`{n}`" not in removed_section}
    assert unnoted == set(), "a released tool disappeared; note the removal"
