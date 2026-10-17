"""HTTP sessions belong to the user who opened them: another user of the same
OAuth client cannot use the session id, and the per-session state (outline
cache, confirm mode) is keyed by the caller too, which also covers the
stateless mode where the transport checks nothing."""

from __future__ import annotations

from types import SimpleNamespace

from fastmcp.server.auth.providers.jwt import JWTVerifier, RSAKeyPair
from fastmcp.server.dependencies import AccessToken
from starlette.testclient import TestClient

from ics_mcp import _helpers
from ics_mcp.config import Settings
from ics_mcp.http_app import build_http_app
from ics_mcp.server import build_mcp

ICS = "https://ics.test"
RESOURCE = "https://mcp.ics.test/mcp"
HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
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
PING = {"jsonrpc": "2.0", "id": 2, "method": "ping"}


def test_another_user_of_the_same_client_cannot_use_the_session():
    settings = Settings(base_url=ICS, mcp_resource_uri=RESOURCE, mcp_transport="http")
    keys = RSAKeyPair.generate()
    verifier = JWTVerifier(
        public_key=keys.public_key, issuer=ICS, audience=RESOURCE, algorithm="RS256"
    )
    app = build_http_app(build_mcp(settings, token_verifier=verifier), settings)

    def bearer(sub: str) -> dict[str, str]:
        token = keys.create_token(
            subject=sub, issuer=ICS, audience=RESOURCE, additional_claims={"client_id": "claude"}
        )
        return {**HEADERS, "authorization": f"Bearer {token}"}

    with TestClient(app, base_url="https://mcp.ics.test") as client:
        opened = client.post("/mcp", json=INIT, headers=bearer("alice"))
        assert opened.status_code == 200
        sid = opened.headers["mcp-session-id"]

        foreign = client.post("/mcp", json=PING, headers={**bearer("bob"), "mcp-session-id": sid})
        own = client.post("/mcp", json=PING, headers={**bearer("alice"), "mcp-session-id": sid})

    assert foreign.status_code == 404
    assert own.status_code == 200


def _as(monkeypatch, sub: str | None, token: str = "t") -> None:
    claims = {"iss": ICS, "sub": sub} if sub else {}
    monkeypatch.setattr(
        _helpers,
        "get_access_token",
        lambda: AccessToken(token=token, client_id="claude", scopes=["ics"], claims=claims),
    )


def test_session_state_is_keyed_by_the_caller(monkeypatch):
    ctx = SimpleNamespace(session_id="shared-session")
    outline = {"headings": [{"title": "Private plan"}]}

    _as(monkeypatch, "alice")
    _helpers.store_outline(ctx, "plan", outline)  # type: ignore[arg-type]
    assert _helpers.cached_outline(ctx, "plan") == outline  # type: ignore[arg-type]

    _as(monkeypatch, "bob")
    assert _helpers.cached_outline(ctx, "plan") is None  # type: ignore[arg-type]
    assert _helpers.session_key(ctx) != "sid:shared-session"  # type: ignore[arg-type]


def test_a_token_without_subject_keys_by_the_token(monkeypatch):
    ctx = SimpleNamespace(session_id="shared-session")
    _as(monkeypatch, None, token="token-a")
    first = _helpers.session_key(ctx)  # type: ignore[arg-type]
    _as(monkeypatch, None, token="token-b")
    assert _helpers.session_key(ctx) != first  # type: ignore[arg-type]


def test_stdio_keeps_one_session(monkeypatch):
    monkeypatch.setattr(_helpers, "get_access_token", lambda: None)
    assert _helpers.session_key(SimpleNamespace(session_id=None)) == "sid:stdio"  # type: ignore[arg-type]
