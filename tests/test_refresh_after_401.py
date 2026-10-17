"""A Bearer challenge refreshes the token instead of forcing a new login."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from ics_mcp.auth.token_store import TokenPair, TokenStore
from ics_mcp.errors import ICSError
from ics_mcp.ics_client import ICSClient

ICS = "https://ics.test"
TOKEN_URL = f"{ICS}/api/auth/oauth/token"
CHALLENGE = {"WWW-Authenticate": 'Bearer error="invalid_token"'}


def _pair(access: str, refresh: str = "refresh-1") -> TokenPair:
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_at=10_000_000_000.0,
        scope="ics",
        resource=f"{ICS}/mcp",
    )


@pytest.fixture
def store(tmp_path):
    s = TokenStore(service=f"ics-mcp-test-{tmp_path.name}", fallback_path=tmp_path / "creds")
    s.save(_pair("old-access"))
    yield s
    s.delete()


@pytest.fixture
async def client(settings, store, monkeypatch):
    login = AsyncMock(side_effect=AssertionError("interactive login must not run"))
    monkeypatch.setattr("ics_mcp.ics_client.stdio_login", login)
    http = httpx.AsyncClient()
    c = ICSClient(settings, store, http)
    c.login_mock = login
    yield c
    await http.aclose()


def _token_response(access: str, **extra):
    return httpx.Response(
        200,
        json={"access_token": access, "expires_in": 3600, "token_type": "Bearer", **extra},
    )


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_bearer_challenge_refreshes_and_retries(client, store, respx_mock):
    api = respx_mock.get(f"{ICS}/api/x").mock(
        side_effect=[httpx.Response(401, headers=CHALLENGE), httpx.Response(200, json={"ok": 1})]
    )
    token = respx_mock.post(TOKEN_URL).mock(
        return_value=_token_response("new-access", refresh_token="refresh-2")
    )
    assert await client.get_json("/api/x") == {"ok": 1}
    assert token.call_count == 1
    assert api.calls[1].request.headers["Authorization"] == "Bearer new-access"
    assert store.load().refresh_token == "refresh-2"
    client.login_mock.assert_not_called()


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_application_401_without_challenge_keeps_the_token(client, store, respx_mock):
    respx_mock.post(f"{ICS}/api/share/t/resolve").mock(
        return_value=httpx.Response(401, json={"detail": "password required"})
    )
    token = respx_mock.post(TOKEN_URL)
    with pytest.raises(Exception):  # noqa: B017 - only the store matters here
        await client.post_json("/api/share/t/resolve", {})
    assert token.call_count == 0
    assert store.load().access_token == "old-access"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_refresh_keeps_refresh_token_when_server_does_not_rotate(client, store, respx_mock):
    respx_mock.get(f"{ICS}/api/x").mock(
        side_effect=[httpx.Response(401, headers=CHALLENGE), httpx.Response(200, json={})]
    )
    respx_mock.post(TOKEN_URL).mock(return_value=_token_response("new-access"))
    await client.get_json("/api/x")
    assert store.load().refresh_token == "refresh-1"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_concurrent_challenges_refresh_once(client, respx_mock):
    calls = {"n": 0}

    def api_handler(request):
        if request.headers["Authorization"] == "Bearer old-access":
            return httpx.Response(401, headers=CHALLENGE)
        return httpx.Response(200, json={})

    async def token_handler(request):
        calls["n"] += 1
        await asyncio.sleep(0.01)
        return _token_response("new-access", refresh_token="refresh-2")

    respx_mock.get(f"{ICS}/api/x").mock(side_effect=api_handler)
    respx_mock.post(TOKEN_URL).mock(side_effect=token_handler)
    await asyncio.gather(client.get_json("/api/x"), client.get_json("/api/x"))
    assert calls["n"] == 1


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_second_challenge_after_refresh_is_an_error_not_a_loop(client, respx_mock):
    api = respx_mock.get(f"{ICS}/api/x").mock(
        return_value=httpx.Response(401, headers=CHALLENGE, json={"detail": "nope"})
    )
    token = respx_mock.post(TOKEN_URL).mock(return_value=_token_response("new-access"))
    with pytest.raises(ICSError) as exc:
        await client.get_json("/api/x")
    assert exc.value.code == "unauthorized"
    assert api.call_count == 2
    assert token.call_count == 1
    client.login_mock.assert_not_called()


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_failed_refresh_drops_the_pair_and_falls_back_to_login(client, store, respx_mock):
    client.login_mock.side_effect = None
    client.login_mock.return_value = _pair("login-access")
    api = respx_mock.get(f"{ICS}/api/x").mock(
        side_effect=[httpx.Response(401, headers=CHALLENGE), httpx.Response(200, json={})]
    )
    respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    await client.get_json("/api/x")
    assert store.load_fresh() is None
    client.login_mock.assert_awaited_once()
    assert api.calls[1].request.headers["Authorization"] == "Bearer login-access"


@pytest.mark.asyncio
@respx.mock(assert_all_called=True)
async def test_expired_pair_is_refreshed_before_the_request(client, store, respx_mock):
    store.save(TokenPair("stale", "refresh-1", expires_at=0.0, scope="ics", resource=f"{ICS}/mcp"))
    respx_mock.post(TOKEN_URL).mock(return_value=_token_response("new-access"))
    api = respx_mock.get(f"{ICS}/api/x").mock(return_value=httpx.Response(200, json={}))
    await client.get_json("/api/x")
    assert api.calls[0].request.headers["Authorization"] == "Bearer new-access"
    client.login_mock.assert_not_called()


@pytest.fixture
async def http_client(settings, store, monkeypatch):
    """ICSClient in HTTP transport mode, forwarding the caller's token."""
    http_settings = settings.model_copy(update={"mcp_transport": "http"})
    http = httpx.AsyncClient()
    c = ICSClient(http_settings, store, http)
    yield c
    await http.aclose()


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_http_transport_challenge_is_returned_to_the_caller(
    http_client, store, respx_mock, monkeypatch
):
    monkeypatch.setattr(
        "ics_mcp.ics_client.get_access_token", lambda: SimpleNamespace(token="caller-token")
    )
    api = respx_mock.get(f"{ICS}/api/x").mock(return_value=httpx.Response(401, headers=CHALLENGE))
    token = respx_mock.post(TOKEN_URL)
    with pytest.raises(ICSError) as exc:
        await http_client.get_json("/api/x")
    assert exc.value.code == "auth_required"
    assert exc.value.status == 401
    assert api.calls[0].request.headers["Authorization"] == "Bearer caller-token"
    assert token.call_count == 0
    assert store.load_fresh().access_token == "old-access"


@pytest.mark.asyncio
async def test_http_transport_without_caller_token_is_rejected(http_client, monkeypatch):
    monkeypatch.setattr("ics_mcp.ics_client.get_access_token", lambda: None)
    with pytest.raises(ICSError) as exc:
        await http_client.get_json("/api/x")
    assert exc.value.code == "auth_required"
