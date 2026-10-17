"""ICSClient tests: HTTP error mapping + retry policy.

Without these tests every refactor of the retry layer is unverified, and
the LLM-facing error codes that agents rely on for control flow can
silently drift.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from ics_mcp.auth.token_store import TokenPair, TokenStore
from ics_mcp.errors import ICSError
from ics_mcp.ics_client import ICSClient


@pytest.fixture
def fresh_token() -> TokenPair:
    """Token that doesn't trigger refresh, used for happy-path testing."""
    return TokenPair(
        access_token="header.payload.sig",
        refresh_token="opaque",
        expires_at=10_000_000_000.0,
        scope="ics",
        resource="https://ics.test/mcp",
    )


@pytest.fixture
def store(tmp_path, fresh_token) -> TokenStore:
    s = TokenStore(service=f"ics-mcp-test-{tmp_path.name}", fallback_path=tmp_path / "creds")
    s.save(fresh_token)
    yield s
    s.delete()


@pytest.fixture
async def client(settings, store):
    http = httpx.AsyncClient()
    c = ICSClient(settings, store, http)
    yield c
    await http.aclose()


# ============================================================
#  _map_error: status -> code
# ============================================================


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_map_error_404_to_not_found(client, respx_mock):
    respx_mock.get("https://ics.test/api/x").mock(
        return_value=httpx.Response(404, json={"detail": "no asset"})
    )
    with pytest.raises(ICSError) as exc:
        await client.get_json("/api/x")
    assert exc.value.code == "not_found"
    assert exc.value.status == 404
    assert "no asset" in exc.value.message


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_map_error_403_to_forbidden(client, respx_mock):
    respx_mock.get("https://ics.test/api/x").mock(return_value=httpx.Response(403))
    with pytest.raises(ICSError) as exc:
        await client.get_json("/api/x")
    assert exc.value.code == "forbidden"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_map_error_410_to_gone(client, respx_mock):
    respx_mock.get("https://ics.test/api/x").mock(return_value=httpx.Response(410))
    with pytest.raises(ICSError) as exc:
        await client.get_json("/api/x")
    assert exc.value.code == "gone"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_map_error_422_to_invalid_argument(client, respx_mock):
    respx_mock.get("https://ics.test/api/x").mock(
        return_value=httpx.Response(422, json={"detail": "bad field"})
    )
    with pytest.raises(ICSError) as exc:
        await client.get_json("/api/x")
    assert exc.value.code == "invalid_argument"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_ics_validation_error_is_invalid_argument_with_field(client, respx_mock):
    """FastAPI request validation in ICS gets the code of every other bad
    argument, with the failed field instead of pydantic's list."""
    detail = [
        {"type": "string_too_long", "loc": ["body", "note"], "msg": "String too long"},
        {"type": "missing", "loc": ["body", "role"], "msg": "Field required"},
    ]
    respx_mock.post("https://ics.test/api/x").mock(
        return_value=httpx.Response(422, json={"detail": detail, "code": "validation_error"})
    )
    with pytest.raises(ICSError) as exc:
        await client.post_json("/api/x", {})
    assert exc.value.code == "invalid_argument"
    assert exc.value.field == "note"
    assert exc.value.message == "Invalid `note`: String too long."
    assert exc.value.data == {"errors": 2}


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_map_error_unknown_status_to_generic(client, respx_mock):
    respx_mock.get("https://ics.test/api/x").mock(return_value=httpx.Response(418))
    with pytest.raises(ICSError) as exc:
        await client.get_json("/api/x")
    assert exc.value.code == "ics_error"
    assert exc.value.status == 418


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_map_error_non_json_response(client, respx_mock):
    respx_mock.get("https://ics.test/api/x").mock(
        return_value=httpx.Response(500, text="plaintext server crash")
    )
    with pytest.raises(ICSError) as exc:
        await client.get_json("/api/x")
    assert exc.value.code == "server_error"


# ============================================================
#  Retry behavior
# ============================================================


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_429_respects_retry_after_and_retries(client, respx_mock):
    route = respx_mock.get("https://ics.test/api/x").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={"detail": "slow"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    out = await client.get_json("/api/x")
    assert out == {"ok": True}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_5xx_transient_triggers_backoff_retry(client, respx_mock, monkeypatch):
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    route = respx_mock.get("https://ics.test/api/x").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    out = await client.get_json("/api/x")
    assert out == {"ok": True}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_500_does_not_retry(client, respx_mock):
    route = respx_mock.get("https://ics.test/api/x").mock(
        return_value=httpx.Response(500, json={"detail": "boom"})
    )
    with pytest.raises(ICSError):
        await client.get_json("/api/x")
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_5xx_gives_up_after_3_attempts(client, respx_mock, monkeypatch):
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    route = respx_mock.get("https://ics.test/api/x").mock(return_value=httpx.Response(503))
    with pytest.raises(ICSError) as exc:
        await client.get_json("/api/x")
    assert exc.value.code in ("ics_error",)
    # Initial + 3 retries
    assert route.call_count == 4


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_network_error_wrapped_as_ics_unreachable(client, respx_mock):
    respx_mock.get("https://ics.test/api/x").mock(side_effect=httpx.ConnectError("dns"))
    with pytest.raises(ICSError) as exc:
        await client.get_json("/api/x")
    assert exc.value.code == "ics_unreachable"
    assert exc.value.status == 502


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_bearer_token_injected_in_authorization_header(client, respx_mock):
    route = respx_mock.get("https://ics.test/api/x").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    await client.get_json("/api/x")
    sent = route.calls.last.request.headers["authorization"]
    assert sent == "Bearer header.payload.sig"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_delete_returns_deleted_marker_on_204(client, respx_mock):
    respx_mock.delete("https://ics.test/api/x").mock(return_value=httpx.Response(204))
    out = await client.delete_json("/api/x")
    assert out == {"deleted": True}


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_post_is_not_retried_on_gateway_error(client, respx_mock, monkeypatch):
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    route = respx_mock.post("https://ics.test/api/assets").mock(return_value=httpx.Response(503))
    with pytest.raises(ICSError) as exc:
        await client.post_json("/api/assets", {"title": "x"})
    assert exc.value.status == 503
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_retry_after_http_date_is_accepted(client, respx_mock, monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("asyncio.sleep", sleep)
    route = respx_mock.get("https://ics.test/api/x").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    assert await client.get_json("/api/x") == {"ok": True}
    assert route.call_count == 2
    sleep.assert_awaited_once_with(0.0)


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_hot_path_reads_the_token_store_at_most_once(client, store, respx_mock, monkeypatch):
    respx_mock.get("https://ics.test/api/x").mock(return_value=httpx.Response(200, json={}))
    reads = {"n": 0}
    real = store.load_fresh

    def counting():
        reads["n"] += 1
        return real()

    monkeypatch.setattr(store, "load_fresh", counting)
    store._cached = None
    for _ in range(10):
        await client.get_json("/api/x")
    assert reads["n"] <= 1
