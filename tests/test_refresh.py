"""Refresh-token grant tests: happy path + failure mapping."""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from ics_mcp.auth.refresh import refresh_token_grant
from ics_mcp.auth.token_store import TokenPair, TokenStore
from ics_mcp.errors import ICSError


@pytest.fixture
def store(tmp_path):
    s = TokenStore(service=f"ics-mcp-rt-{tmp_path.name}", fallback_path=tmp_path / "creds")
    yield s
    s.delete()


@pytest.fixture
def current() -> TokenPair:
    return TokenPair(
        access_token="old.access.jwt",
        refresh_token="old-refresh-opaque",
        expires_at=0.0,
        scope="ics",
        resource="https://ics.test/mcp",
    )


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_refresh_grant_rotates_and_saves(settings, store, current, respx_mock):
    respx_mock.post("https://ics.test/api/auth/oauth/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new.access.jwt",
                "refresh_token": "new-refresh-opaque",
                "expires_in": 3600,
                "scope": "ics",
                "resource": "https://ics.test/mcp",
            },
        )
    )
    new_pair = await refresh_token_grant(settings, store, current)
    assert new_pair.access_token == "new.access.jwt"
    assert new_pair.refresh_token == "new-refresh-opaque"
    assert new_pair.expires_at > time.time()
    # Persisted to store
    loaded = store.load()
    assert loaded is not None
    assert loaded.access_token == "new.access.jwt"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_refresh_grant_failure_raises_ics_error(settings, store, current, respx_mock):
    respx_mock.post("https://ics.test/api/auth/oauth/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(ICSError) as exc:
        await refresh_token_grant(settings, store, current)
    assert exc.value.code == "refresh_failed"
    assert exc.value.status == 400


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_refresh_grant_uses_shared_http_when_provided(settings, store, current, respx_mock):
    """Caller can pass `http=...` to skip the per-call AsyncClient overhead."""
    respx_mock.post("https://ics.test/api/auth/oauth/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "a",
                "refresh_token": "b",
                "expires_in": 60,
                "scope": "ics",
                "resource": "https://ics.test/mcp",
            },
        )
    )
    async with httpx.AsyncClient() as shared:
        new_pair = await refresh_token_grant(settings, store, current, http=shared)
        assert new_pair.access_token == "a"
        # The caller's client stays open; the caller still needs it.
        assert shared.is_closed is False


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_refresh_grant_non_json_error_body_still_caught(settings, store, current, respx_mock):
    respx_mock.post("https://ics.test/api/auth/oauth/token").mock(
        return_value=httpx.Response(503, text="upstream down")
    )
    with pytest.raises(ICSError) as exc:
        await refresh_token_grant(settings, store, current)
    assert exc.value.status == 503
