"""Profiles and processes sharing a token store: each keyring service gets
its own fallback file, and two processes refreshing the same expired pair
spend the refresh token once, with neither losing the fresh pair."""

from __future__ import annotations

import asyncio

import httpx
import keyring
import pytest
import respx

from ics_mcp.auth.token_store import TokenPair, TokenStore
from ics_mcp.config import Settings
from ics_mcp.ics_client import ICSClient

ICS = "https://ics.test"
TOKEN_URL = f"{ICS}/api/auth/oauth/token"


def test_each_keyring_service_has_its_own_fallback_file():
    default = Settings(base_url=ICS).token_fallback_path_resolved
    work = Settings(base_url=ICS, mcp_keyring_service="ics-mcp-work").token_fallback_path_resolved
    odd = Settings(base_url=ICS, mcp_keyring_service="a/b c").token_fallback_path_resolved

    assert default.name == "credentials.json"
    assert work.name == "credentials-ics-mcp-work.json"
    assert odd.name == "credentials-a_b_c.json"
    assert len({default, work, odd}) == 3


@pytest.fixture
def no_keyring(monkeypatch):
    def unavailable(*_a, **_k):
        raise keyring.errors.NoKeyringError

    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, unavailable)


def _expired() -> TokenPair:
    return TokenPair(
        access_token="old.access",
        refresh_token="old-refresh",
        expires_at=0.0,
        scope="ics",
        resource=f"{ICS}/mcp",
    )


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_two_processes_refresh_the_shared_pair_once(
    tmp_path, respx_mock, monkeypatch, no_keyring
):
    settings = Settings(base_url=ICS, mcp_resource_uri=f"{ICS}/mcp", mcp_oauth_client_id="c")
    path = tmp_path / "credentials.json"
    TokenStore(service="ics-mcp", fallback_path=path).save(_expired())

    calls: list[bytes] = []

    async def server(request: httpx.Request) -> httpx.Response:
        """Rotates `old-refresh` once; a reuse gets `invalid_grant`."""
        calls.append(request.content)
        if len(calls) > 1 or b"refresh_token=old-refresh" not in request.content:
            return httpx.Response(400, json={"error": "invalid_grant"})
        await asyncio.sleep(0.2)  # the other process asks meanwhile
        return httpx.Response(
            200,
            json={
                "access_token": "new.access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
                "scope": "ics",
                "resource": f"{ICS}/mcp",
            },
        )

    respx_mock.post(TOKEN_URL).mock(side_effect=server)

    async def no_login(*_a, **_k):
        raise AssertionError("an interactive login was started")

    monkeypatch.setattr("ics_mcp.ics_client.stdio_login", no_login)

    async with httpx.AsyncClient() as http:
        # Separate stores and clients: separate in-process caches and locks,
        # like two ics-mcp processes on one profile.
        first = ICSClient(settings, TokenStore(service="ics-mcp", fallback_path=path), http)
        second = ICSClient(settings, TokenStore(service="ics-mcp", fallback_path=path), http)
        a, b = await asyncio.gather(first._ensure_token(), second._ensure_token())

    assert len(calls) == 1
    assert a.access_token == b.access_token == "new.access"
    stored = TokenStore(service="ics-mcp", fallback_path=path).load_fresh()
    assert stored is not None and stored.refresh_token == "new-refresh"
