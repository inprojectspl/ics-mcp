"""Session-management + meta tools (help, whoami, mode)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastmcp import Context, FastMCP

from ics_mcp import models as M
from ics_mcp import session as session_mod
from ics_mcp._helpers import map_ics_errors, session_key
from ics_mcp._runtime import runtime
from ics_mcp.config import get_settings
from ics_mcp.errors import ICSError
from ics_mcp.tools._annotations import MUTATING_IDEMP, RO_IDEMP
from ics_mcp.version import PROTOCOL_VERSION, SERVER_INFO

_HELP_DIR = Path(__file__).resolve().parents[1] / "help_md"


@lru_cache(maxsize=8)
def _help_content(topic: str) -> str:
    path = _HELP_DIR / f"{topic}.md"
    return path.read_text(encoding="utf-8") if path.exists() else f"# {topic}\n\n(missing)"


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ics_help",
        title="ICS-MCP help",
        description=(
            "Markdown documentation for ICS-MCP. Topics:\n"
            "- `overview`: what it is, data model, main paths.\n"
            "- `workflows`: common scenarios (create+share, edit, batch).\n"
            "- `tools`: cheat sheet of all tools.\n"
            "- `tool-selection`: decision tree for choosing between two "
            "tools (search vs list, update vs new_version, link vs grant).\n"
            "- `confirm`: `confirm` semantics and session modes "
            "(interactive/yolo/dry_run).\n"
            "- `auth`: OAuth flow, rate limits, audience binding.\n"
            "- `graph`: relation types and walking the document graph.\n"
            "- `task-context`: documents of a task, task links, project links.\n\n"
            "Without an argument returns `overview`. Call `tool-selection` "
            "when unsure which of two tools to use."
        ),
        annotations=RO_IDEMP,
    )
    async def ics_help(
        topic: Literal[
            "overview",
            "workflows",
            "tools",
            "tool-selection",
            "confirm",
            "auth",
            "graph",
            "task-context",
        ] = "overview",
    ) -> M.HelpOut:
        return M.HelpOut(topic=topic, content_markdown=_help_content(topic))

    @mcp.tool(
        name="ics_whoami",
        title="Current signed-in user",
        description="Information about the user, the token and the OAuth client.",
        annotations=RO_IDEMP,
    )
    @map_ics_errors
    async def ics_whoami() -> M.WhoamiOut:
        return M.WhoamiOut(**(await runtime.require_ics().whoami()))

    @mcp.tool(
        name="ics_session_set_mode",
        title="Set session mode",
        description=(
            "Modes (each lasts until the end of the MCP session or the next "
            "`set_mode`):\n"
            "- `interactive`: destructive tools ask the user.\n"
            "- `yolo`: no questions, everything runs. For autonomous "
            "agents. ⚠️ Lasts until the end of the session, remember to reset it.\n"
            "- `dry_run`: preview of destructive operations, nothing "
            "changes in ICS.\n\n"
            "Per-call override: the `confirm=True/False` argument of a "
            "destructive tool overrides the session mode. "
            "Check the current mode: `ics_session_status`."
        ),
        annotations=MUTATING_IDEMP,
    )
    @map_ics_errors
    async def ics_session_set_mode(ctx: Context, mode: M.ConfirmModeArg) -> M.SessionStatusOut:
        settings = get_settings()
        if mode == "yolo" and not (
            settings.mcp_allow_yolo or settings.mcp_default_confirm == "yolo"
        ):
            raise ICSError(
                "yolo_disabled",
                "Switching the session to yolo is disabled on this server.",
                hint="Pass confirm=true per call, or ask the operator to set ICS_MCP_ALLOW_YOLO=true.",
            )
        state = session_mod.state_for(session_key(ctx))
        state.confirm_mode = mode
        return M.SessionStatusOut(
            mode=state.confirm_mode,
            server_version=SERVER_INFO["version"],
            protocol_version=PROTOCOL_VERSION,
        )

    @mcp.tool(
        name="ics_session_status",
        title="Session status",
        description="Current session mode plus server and protocol versions.",
        annotations=RO_IDEMP,
    )
    async def ics_session_status(ctx: Context) -> M.SessionStatusOut:
        state = session_mod.state_for(session_key(ctx))
        return M.SessionStatusOut(
            mode=state.confirm_mode,
            server_version=SERVER_INFO["version"],
            protocol_version=PROTOCOL_VERSION,
        )
