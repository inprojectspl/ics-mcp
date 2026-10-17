"""The server's own guidance for agents stays consistent: instructions, tool
descriptions and help pages give the same reading rule and point to the task
and graph tools."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ics_mcp.server import build_mcp
from tests.conftest import list_tools


def test_server_instructions_point_to_tasks_and_the_graph():
    from ics_mcp.version import INSTRUCTIONS

    assert "ics_task_context" in INSTRUCTIONS
    assert "ics_graph_neighbourhood" in INSTRUCTIONS


@pytest.mark.asyncio
async def test_one_reading_rule_everywhere(settings):
    """Every text that tells an agent how to read gives the same rule: whole
    up to 800 estimated tokens or when most of it is needed, otherwise the
    outline without edges, then a section."""
    from ics_mcp.version import INSTRUCTIONS

    help_dir = Path(__file__).resolve().parent.parent / "ics_mcp" / "help_md"
    tools = {t.name: t for t in await list_tools(build_mcp(settings))}
    texts = {
        "instructions": INSTRUCTIONS,
        **{
            name: tools[name].description or ""
            for name in ("ics_asset_read", "ics_asset_outline", "ics_task_context")
        },
        **{
            page: (help_dir / f"{page}.md").read_text(encoding="utf-8")
            for page in ("overview", "tool-selection", "task-context", "graph")
        },
    }
    for name, text in texts.items():
        assert re.search(r"(?<!\d)800 `?estimated_tokens", text), name
        assert "most of it" in text, name
        assert "edges" in text, name
        assert "1500" not in text, name
        for stale in ("Order of preference", "read the outline first", "start with outline"):
            assert stale not in text.replace("`", ""), (name, stale)
