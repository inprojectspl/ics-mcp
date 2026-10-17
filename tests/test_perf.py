"""Performance-oriented behaviors:
- `resolve_id_cached` saves round-trips inside a session.
- `progress_scope` throttles tick emissions.
- `maybe_truncate` shrinks oversized payloads.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from ics_mcp import session as session_mod
from ics_mcp._helpers import invalidate_slug_cache, resolve_id_cached
from ics_mcp._payload import maybe_truncate
from ics_mcp.progress import progress_scope
from tests.conftest import ASSET_ID, ICS

# ============================================================
#  resolve_id_cached
# ============================================================


@pytest.fixture
def ctx_fixed():
    """Context with stable session_id so cache key is deterministic."""
    c = MagicMock()
    c.session_id = "perf-test"
    return c


@pytest.fixture(autouse=True)
def _clear_session_store():
    session_mod.clear_all()


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resolve_id_cached_avoids_second_roundtrip(real_client, respx_mock, ctx_fixed):
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "slug": "abc"})
    )
    assert await resolve_id_cached(ctx_fixed, "abc") == ASSET_ID
    assert await resolve_id_cached(ctx_fixed, "abc") == ASSET_ID
    assert await resolve_id_cached(ctx_fixed, "abc") == ASSET_ID
    assert route.call_count == 1, "second+ calls should hit session cache"


@pytest.mark.asyncio
async def test_resolve_id_cached_passes_uuid_through(ctx_fixed):
    """UUID inputs skip the cache entirely; no ICS round-trip needed."""
    assert await resolve_id_cached(ctx_fixed, ASSET_ID) == ASSET_ID


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_invalidate_slug_cache_forces_refetch(real_client, respx_mock, ctx_fixed):
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "slug": "abc"})
    )
    await resolve_id_cached(ctx_fixed, "abc")
    invalidate_slug_cache(ctx_fixed, "abc")
    await resolve_id_cached(ctx_fixed, "abc")
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_resolve_id_cached_isolated_per_session(real_client, respx_mock):
    ctx_a = MagicMock()
    ctx_a.session_id = "agent-a"
    ctx_b = MagicMock()
    ctx_b.session_id = "agent-b"
    route = respx_mock.get(f"{ICS}/api/assets/by-slug/abc/meta").mock(
        return_value=httpx.Response(200, json={"id": ASSET_ID, "slug": "abc"})
    )
    await resolve_id_cached(ctx_a, "abc")
    await resolve_id_cached(ctx_b, "abc")
    assert route.call_count == 2, "different sessions shouldn't share cache"


# ============================================================
#  progress_scope throttling
# ============================================================


class _CountingCtx:
    def __init__(self):
        self.progress_calls: list[tuple[int, int | None, str | None]] = []

    async def report_progress(self, *, progress, total=None, message=None):
        self.progress_calls.append((progress, total, message))

    async def info(self, _msg: str):
        return None


@pytest.mark.asyncio
async def test_progress_scope_throttles_rapid_ticks():
    """50 ticks in a tight loop should collapse to a handful of emissions
    plus the mandatory final `done`."""
    ctx = _CountingCtx()
    async with progress_scope(ctx, total=50, message="bundle") as tick:
        for _ in range(50):
            await tick(1)
    # Throttle window 100 ms: a tight loop runs in well under that, so
    # the only emissions we expect are: first tick (last_emit_ms=0) +
    # the mandatory final `done`. The middle ticks are dropped.
    assert len(ctx.progress_calls) <= 5, f"expected throttled ticks, got {len(ctx.progress_calls)}"
    # Final tick must report `progress == total` regardless.
    final = ctx.progress_calls[-1]
    assert final[0] == 50 and final[2] == "done"


@pytest.mark.asyncio
async def test_progress_scope_emits_after_throttle_window():
    """Ticks separated by >100 ms each get emitted."""
    ctx = _CountingCtx()
    async with progress_scope(ctx, total=3, message="slow") as tick:
        await tick(1)
        await asyncio.sleep(0.12)
        await tick(1)
        await asyncio.sleep(0.12)
        await tick(1)
    # 3 throttled ticks + 1 final done, but the very last tick may
    # equal `done` so allow either 3 or 4.
    assert 3 <= len(ctx.progress_calls) <= 4


# ============================================================
#  maybe_truncate
# ============================================================


def test_maybe_truncate_passes_small_payload_unchanged():
    payload = {"x": "hi"}
    assert maybe_truncate(payload) == payload


def test_maybe_truncate_shrinks_oversized_payload():
    big = {"data": "x" * 20_000, "kind": "md_collection", "files": [1, 2, 3]}
    out = maybe_truncate(big, max_chars=8000)
    assert out["truncated"] is True
    assert out["original_size_chars"] > 8000
    assert "shape" in out
    # Shape preserves top-level structure for the agent to pick the right
    # follow-up tool without paying the full payload cost.
    assert out["shape"]["data"]["type"] == "str"
    assert out["shape"]["data"]["len"] > 8000
    assert out["shape"]["files"] == {"type": "list", "len": 3}
    assert "ics_asset_outline" in out["hint"]


def test_maybe_truncate_respects_custom_cap():
    payload = {"data": "x" * 100}
    not_truncated = maybe_truncate(payload, max_chars=10_000)
    assert "truncated" not in not_truncated
    truncated = maybe_truncate(payload, max_chars=20)
    assert truncated["truncated"] is True
