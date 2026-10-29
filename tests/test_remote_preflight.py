"""Remote preflight detects routing/OAuth metadata failures without credentials or writes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import httpx
import pytest
from fastmcp.server.auth.providers.jwt import JWTVerifier, RSAKeyPair

from ics_mcp.config import Settings
from ics_mcp.http_app import build_http_app
from ics_mcp.server import build_mcp
from scripts.check_remote import _protected_resource, check_remote, main

ISSUER = "https://ics.test"
MCP = "https://mcp.ics.test/mcp"
PROTECTED_URL = "https://mcp.ics.test/.well-known/oauth-protected-resource/mcp"
AUTH_URL = f"{ISSUER}/.well-known/oauth-authorization-server"
HEALTH_URL = "https://mcp.ics.test/health"


def metadata() -> dict[str, Any]:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/api/auth/oauth/authorize",
        "token_endpoint": f"{ISSUER}/api/auth/oauth/token",
        "registration_endpoint": f"{ISSUER}/api/auth/oauth/register",
        "jwks_uri": f"{ISSUER}/api/auth/oauth/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["ics"],
    }


def responses() -> dict[str, httpx.Response]:
    return {
        PROTECTED_URL: httpx.Response(
            200, json={"resource": MCP, "authorization_servers": [ISSUER]}
        ),
        AUTH_URL: httpx.Response(200, json=metadata()),
        HEALTH_URL: httpx.Response(200, json={"status": "ok"}),
    }


def mock_client(
    replies: dict[str, httpx.Response], seen: list[httpx.Request] | None = None
) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        assert request.method == "GET"
        assert "authorization" not in request.headers
        return replies[str(request.url)]

    return httpx.Client(transport=httpx.MockTransport(respond))


def test_success_uses_only_three_anonymous_gets():
    seen: list[httpx.Request] = []
    with mock_client(responses(), seen) as client:
        checks = check_remote(client, mcp_url=MCP, issuer=ISSUER)
    assert all(check.passed for check in checks)
    assert [str(request.url) for request in seen] == [PROTECTED_URL, AUTH_URL, HEALTH_URL]


@pytest.mark.asyncio
async def test_preflight_accepts_metadata_serialized_by_http_server():
    settings = Settings(base_url=ISSUER, mcp_resource_uri=MCP, mcp_transport="http")
    keys = RSAKeyPair.generate()
    verifier = JWTVerifier(
        public_key=keys.public_key, issuer=ISSUER, audience=MCP, algorithm="RS256"
    )
    app = build_http_app(build_mcp(settings, token_verifier=verifier), settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        response = await client.get(PROTECTED_URL)
    assert response.status_code == 200
    assert response.json()["authorization_servers"] == [f"{ISSUER}/"]
    replies = responses()
    replies[PROTECTED_URL] = httpx.Response(200, json=response.json())
    with mock_client(replies) as client:
        checks = check_remote(client, mcp_url=MCP, issuer=ISSUER)
    assert all(check.passed for check in checks)


@pytest.mark.parametrize(
    ("issuer", "advertised"),
    [(f"{ISSUER}/tenant", f"{ISSUER}/tenant/"), (f"{ISSUER}/tenant/", f"{ISSUER}/tenant")],
)
def test_authorization_servers_keeps_path_trailing_slashes_significant(issuer, advertised):
    body = {"resource": MCP, "authorization_servers": [advertised]}
    with pytest.raises(ValueError, match="authorization_servers"):
        _protected_resource(body, MCP, issuer)


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (httpx.Response(200, text="<html>private-session-value</html>"), "Expected JSON"),
        (
            httpx.Response(302, headers={"location": "/login?token=private-session-value"}),
            "HTTP 302",
        ),
        (
            httpx.Response(200, content=b"broken", headers={"content-type": "application/json"}),
            "invalid JSON",
        ),
        (httpx.Response(200, json=[]), "Expected a JSON object"),
    ],
)
def test_bad_root_discovery_is_reported_without_body_or_redirect(reply, message):
    replies = responses()
    replies[AUTH_URL] = reply
    with mock_client(replies) as client:
        checks = check_remote(client, mcp_url=MCP, issuer=ISSUER)
    assert not checks[1].passed
    assert message in checks[1].message
    assert "private-session-value" not in str(checks)
    assert checks[0].passed and checks[2].passed


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("issuer", "https://other.test", "issuer does not match"),
        ("issuer", f"{ISSUER}/", "issuer does not match"),
        ("registration_endpoint", None, "Missing registration_endpoint"),
        ("code_challenge_methods_supported", ["plain"], "does not advertise S256"),
        ("scopes_supported", [], "does not advertise ics"),
        (
            "token_endpoint_auth_methods_supported",
            ["client_secret_basic"],
            "does not advertise none",
        ),
        (
            "token_endpoint",
            "https://user:private-session-value@ics.test/token",
            "without credentials",
        ),
    ],
)
def test_authorization_contract_errors(field, value, message):
    data = deepcopy(metadata())
    data[field] = value
    replies = responses()
    replies[AUTH_URL] = httpx.Response(200, json=data)
    with mock_client(replies) as client:
        checks = check_remote(client, mcp_url=MCP, issuer=ISSUER)
    assert not checks[1].passed
    assert message in checks[1].message
    assert "private-session-value" not in str(checks)


@pytest.mark.parametrize(
    "resource",
    ["https://mcp.ics.test/mcp/", "https://wrong.test/mcp"],
)
def test_resource_audience_requires_exact_match(resource):
    replies = responses()
    replies[PROTECTED_URL] = httpx.Response(
        200, json={"resource": resource, "authorization_servers": [ISSUER]}
    )
    with mock_client(replies) as client:
        checks = check_remote(client, mcp_url=MCP, issuer=ISSUER)
    assert not checks[0].passed
    assert "ICS_MCP_RESOURCE_URI" in checks[0].message


def test_wrong_advertised_authority_and_unhealthy_process_fail_independently():
    replies = responses()
    replies[PROTECTED_URL] = httpx.Response(
        200, json={"resource": MCP, "authorization_servers": ["https://other.test"]}
    )
    replies[HEALTH_URL] = httpx.Response(200, json={"status": "degraded"})
    with mock_client(replies) as client:
        checks = check_remote(client, mcp_url=MCP, issuer=ISSUER)
    assert [check.passed for check in checks] == [False, True, False]


def test_network_failure_does_not_print_exception_details():
    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private-session-value", request=request)

    with httpx.Client(transport=httpx.MockTransport(unavailable)) as client:
        checks = check_remote(client, mcp_url=MCP, issuer=ISSUER)
    assert not any(check.passed for check in checks)
    assert all("ConnectError" in check.message for check in checks)
    assert "private-session-value" not in str(checks)


@pytest.mark.parametrize(
    "url",
    ["ics.test", "file:///tmp/config", "https://user:secret@ics.test", "https://ics.test/?token=x"],
)
def test_invalid_input_is_rejected_before_network_request(url):
    with mock_client({}) as client, pytest.raises(ValueError, match="absolute HTTP"):
        check_remote(client, mcp_url=url, issuer=ISSUER)


@pytest.mark.parametrize("healthy", [True, False])
def test_cli_exit_code_and_output(monkeypatch, capsys, healthy):
    replies = responses()
    if not healthy:
        replies[AUTH_URL] = httpx.Response(200, text="<html>private-session-value</html>")
    client = mock_client(replies)
    monkeypatch.setattr("scripts.check_remote.httpx.Client", lambda **_: client)
    status = main(["--mcp-url", MCP, "--issuer", ISSUER])
    output = capsys.readouterr().out
    assert status == (0 if healthy else 1)
    assert "Anonymous GET checks only" in output
    assert "private-session-value" not in output


def test_private_health_endpoint_is_a_warning_not_a_connection_failure(monkeypatch, capsys):
    replies = responses()
    replies[HEALTH_URL] = httpx.Response(404)
    client = mock_client(replies)
    monkeypatch.setattr("scripts.check_remote.httpx.Client", lambda **_: client)
    assert main(["--mcp-url", MCP, "--issuer", ISSUER]) == 0
    assert "WARN MCP health" in capsys.readouterr().out
