"""Confirm-flow unit tests: all three modes + decline paths.

`confirm_or_skip` is the destructive-tool gate; if it misbehaves agents
silently bypass user consent. Tests cover every branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from ics_mcp.confirm import confirm_or_skip
from ics_mcp.errors import ICSError


@dataclass
class _ElicitResult:
    action: str
    data: dict[str, Any] | None = None


class FakeContext:
    """Bare-bones Context double; exposes only what confirm_or_skip uses."""

    def __init__(
        self, elicit_result: _ElicitResult | None = None, raise_on_elicit: Exception | None = None
    ):
        self._elicit_result = elicit_result
        self._raise = raise_on_elicit
        self.elicit_calls: list[dict[str, Any]] = []

    async def elicit(self, *, message: str, response_type: Any) -> Any:
        self.elicit_calls.append({"message": message, "response_type": response_type})
        if self._raise:
            raise self._raise
        return self._elicit_result


@pytest.mark.asyncio
async def test_yolo_skips_prompt_returns_none():
    ctx = FakeContext()
    result = await confirm_or_skip(ctx, action="delete", target="abc", confirm=None, mode="yolo")
    assert result is None
    assert ctx.elicit_calls == []


@pytest.mark.asyncio
async def test_dry_run_returns_preview_dict_without_eliciting():
    ctx = FakeContext()
    result = await confirm_or_skip(
        ctx, action="delete_asset", target="my-slug", confirm=None, mode="dry_run"
    )
    assert isinstance(result, dict)
    assert result["action"] == "delete_asset"
    assert result["target"] == "my-slug"
    assert "dry_run" in result["note"]
    assert ctx.elicit_calls == []


@pytest.mark.asyncio
async def test_explicit_confirm_true_skips_prompt():
    ctx = FakeContext()
    result = await confirm_or_skip(ctx, action="x", target="y", confirm=True, mode="interactive")
    assert result is None
    assert ctx.elicit_calls == []


@pytest.mark.asyncio
async def test_explicit_confirm_false_raises_confirm_required():
    ctx = FakeContext()
    with pytest.raises(ICSError) as exc:
        await confirm_or_skip(ctx, action="x", target="y", confirm=False, mode="interactive")
    assert exc.value.code == "confirm_required"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["yolo", "dry_run"])
async def test_explicit_confirm_false_beats_session_mode(mode):
    """The 'argument > session mode' contract: an explicit refusal must win
    over every mode. yolo would run the operation, dry_run would return a
    preview that looks like success."""
    ctx = FakeContext()
    with pytest.raises(ICSError) as exc:
        await confirm_or_skip(ctx, action="delete", target="abc", confirm=False, mode=mode)
    assert exc.value.code == "confirm_required"
    assert ctx.elicit_calls == []


@pytest.mark.asyncio
async def test_interactive_accept_returns_none():
    ctx = FakeContext(elicit_result=_ElicitResult(action="accept", data={"confirm": True}))
    result = await confirm_or_skip(
        ctx, action="delete", target="abc", confirm=None, mode="interactive"
    )
    assert result is None
    assert len(ctx.elicit_calls) == 1
    assert "delete" in ctx.elicit_calls[0]["message"]
    assert "abc" in ctx.elicit_calls[0]["message"]


@pytest.mark.asyncio
async def test_interactive_accept_but_unchecked_raises_declined():
    """User clicked OK on the modal but left the checkbox at False: still declines."""
    ctx = FakeContext(elicit_result=_ElicitResult(action="accept", data={"confirm": False}))
    with pytest.raises(ICSError) as exc:
        await confirm_or_skip(ctx, action="delete", target="abc", confirm=None, mode="interactive")
    assert exc.value.code == "confirm_declined"


@pytest.mark.asyncio
async def test_interactive_decline_action_raises():
    ctx = FakeContext(elicit_result=_ElicitResult(action="decline"))
    with pytest.raises(ICSError) as exc:
        await confirm_or_skip(ctx, action="delete", target="abc", confirm=None, mode="interactive")
    assert exc.value.code == "confirm_declined"


@pytest.mark.asyncio
async def test_interactive_cancel_action_raises():
    ctx = FakeContext(elicit_result=_ElicitResult(action="cancel"))
    with pytest.raises(ICSError) as exc:
        await confirm_or_skip(ctx, action="delete", target="abc", confirm=None, mode="interactive")
    assert exc.value.code == "confirm_declined"


@pytest.mark.asyncio
async def test_client_without_elicit_capability_raises_confirm_required():
    """If `ctx.elicit` itself blows up (client doesn't declare capability),
    we surface a useful error rather than crashing the agent."""
    ctx = FakeContext(raise_on_elicit=RuntimeError("no elicitation capability"))
    with pytest.raises(ICSError) as exc:
        await confirm_or_skip(ctx, action="delete", target="abc", confirm=None, mode="interactive")
    assert exc.value.code == "confirm_required"
    assert "confirm=true" in (exc.value.hint or "")
    assert "yolo" in (exc.value.hint or "")
    # Message names the operation so the agent knows what needs consent.
    assert "delete" in exc.value.message
    assert "abc" in exc.value.message


def test_confirm_mode_has_single_canonical_definition():
    """config.ConfirmMode is the only definition of the mode Literal and every
    other module re-exports the same object, so copies cannot drift apart."""
    from typing import get_args

    from ics_mcp import confirm, models, session
    from ics_mcp.config import ConfirmMode

    assert set(get_args(ConfirmMode)) == {"interactive", "yolo", "dry_run"}
    assert confirm.ConfirmMode is ConfirmMode
    assert session.ConfirmMode is ConfirmMode
    assert models.ConfirmModeArg is ConfirmMode


def test_config_accepts_legacy_ask_alias(monkeypatch):
    """Existing deploys may still have ICS_MCP_DEFAULT_CONFIRM=ask."""
    from ics_mcp.config import Settings

    monkeypatch.setenv("ICS_MCP_DEFAULT_CONFIRM", "ask")
    assert Settings().mcp_default_confirm == "interactive"


def test_new_sessions_start_in_configured_default_mode(monkeypatch):
    """`ICS_MCP_DEFAULT_CONFIRM` drives the starting mode of a session."""
    from ics_mcp import session as session_mod
    from ics_mcp.config import get_settings

    monkeypatch.setenv("ICS_MCP_DEFAULT_CONFIRM", "yolo")
    get_settings.cache_clear()
    try:
        session_mod.clear_all()
        assert session_mod.state_for("fresh-key").confirm_mode == "yolo"
    finally:
        get_settings.cache_clear()
        session_mod.clear_all()
