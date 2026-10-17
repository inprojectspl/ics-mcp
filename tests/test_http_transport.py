"""HTTP transport: bearer auth, per-caller identity, origin guard, health."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import JWTVerifier, RSAKeyPair
from fastmcp.server.dependencies import AccessToken

from ics_mcp.auth.token_store import TokenStore
from ics_mcp.config import Settings
from ics_mcp.http_app import build_http_app
from ics_mcp.ics_client import ICSClient
from ics_mcp.server import build_mcp

ICS = "https://ics.test"
RESOURCE = "https://mcp.ics.test/mcp"


@pytest.fixture
def http_settings() -> Settings:
    return Settings(
        base_url=ICS,
        mcp_resource_uri=RESOURCE,
        mcp_transport="http",
        mcp_extra_origins="https://claude.ai",
    )


@pytest.fixture
def keys() -> RSAKeyPair:
    return RSAKeyPair.generate()


@pytest.fixture
def app(http_settings, keys):
    verifier = JWTVerifier(
        public_key=keys.public_key, issuer=ICS, audience=RESOURCE, algorithm="RS256"
    )
    return build_http_app(build_mcp(http_settings, token_verifier=verifier), http_settings)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://mcp.ics.test"
    )


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "1"},
    },
}
HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


@pytest.mark.asyncio
async def test_mcp_without_token_gets_401_with_resource_metadata(app):
    async with _client(app) as c:
        r = await c.post("/mcp", json=INIT, headers=HEADERS)
    assert r.status_code == 401
    challenge = r.headers["www-authenticate"]
    assert challenge.startswith("Bearer")
    assert "resource_metadata" in challenge


@pytest.mark.asyncio
async def test_protected_resource_metadata_names_ics(app):
    async with _client(app) as c:
        r = await c.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"] == RESOURCE
    assert [s.rstrip("/") for s in body["authorization_servers"]] == [ICS]


@pytest.mark.asyncio
async def test_token_for_another_audience_is_rejected(app, keys):
    token = keys.create_token(issuer=ICS, audience="https://elsewhere.test/mcp")
    async with _client(app) as c:
        r = await c.post("/mcp", json=INIT, headers={**HEADERS, "authorization": f"Bearer {token}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_foreign_origin_is_refused_and_health_answers(app):
    async with _client(app) as c:
        bad = await c.post("/mcp", json=INIT, headers={**HEADERS, "origin": "https://evil.test"})
        ok_origin = await c.get("/health", headers={"origin": "https://claude.ai"})
        health = await c.get("/health")
    assert bad.status_code == 403
    assert ok_origin.status_code == 200
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_each_caller_reaches_ics_with_its_own_token(
    http_settings, tmp_path, respx_mock, monkeypatch
):
    store = TokenStore(service=f"ics-mcp-test-{tmp_path.name}", fallback_path=tmp_path / "creds")
    route = respx_mock.get(f"{ICS}/api/x").mock(return_value=httpx.Response(200, json={}))
    async with httpx.AsyncClient() as http:
        client = ICSClient(http_settings, store, http)
        for caller in ("token-alice", "token-bob"):
            monkeypatch.setattr(
                "ics_mcp.ics_client.get_access_token",
                lambda caller=caller: AccessToken(token=caller, client_id="c", scopes=["ics"]),
            )
            await client.get_json("/api/x")
    seen = [call.request.headers["Authorization"] for call in route.calls]
    assert seen == ["Bearer token-alice", "Bearer token-bob"]
    assert store.load_fresh() is None


def test_content_path_is_refused_over_http(monkeypatch, tmp_path):
    from ics_mcp._uploads import file_bytes
    from ics_mcp.config import get_settings

    monkeypatch.setattr(get_settings(), "mcp_transport", "http")
    secret = tmp_path / "creds"
    secret.write_text("x")
    with pytest.raises(ToolError) as exc:
        file_bytes(None, None, str(secret))
    assert "invalid_argument" in str(exc.value)


@pytest.mark.asyncio
async def test_valid_token_passes_the_gate(app, keys):
    token = keys.create_token(issuer=ICS, audience=RESOURCE, scopes=["ics"])
    async with app.router.lifespan_context(app), _client(app) as c:
        r = await c.post("/mcp", json=INIT, headers={**HEADERS, "authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_internal_base_url_keeps_the_public_issuer():
    s = Settings(
        base_url="http://backend:8000",
        mcp_oauth_issuer="https://ics.test",
        mcp_resource_uri=RESOURCE,
        mcp_transport="http",
    )
    assert s.issuer == "https://ics.test"
    assert s.jwks_url == "http://backend:8000/api/auth/oauth/jwks.json"
