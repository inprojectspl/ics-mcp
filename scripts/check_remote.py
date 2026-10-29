"""Check public ICS-MCP discovery with anonymous GET requests only.

This operator utility never starts OAuth, registers a client, calls an MCP
tool, or accepts a token. Response bodies and exception details are not
printed because an incorrectly routed endpoint can return private content.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    message: str
    required: bool = True


def _public_url(value: str) -> SplitResult:
    try:
        parts = urlsplit(value)
        valid = (
            parts.scheme in {"http", "https"}
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
            and not parts.query
            and not parts.fragment
        )
        # Accessing port also validates malformed and out-of-range ports.
        _ = parts.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Use an absolute HTTP(S) URL without credentials, query or fragment.")
    return parts


def _url_at(parts: SplitResult, path: str) -> str:
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _get_json(client: httpx.Client, url: str) -> dict[str, Any]:
    try:
        response = client.get(url, headers={"Accept": "application/json"}, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise ValueError(
            f"GET failed ({type(exc).__name__}); check DNS, TLS and routing."
        ) from None
    if response.status_code != 200:
        raise ValueError(
            f"HTTP {response.status_code}; expected public JSON without a sign-in redirect."
        )
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise ValueError("Expected JSON; received HTML or another non-JSON content type.")
    try:
        body = response.json()
    except ValueError:
        raise ValueError("The response declares JSON but contains invalid JSON.") from None
    if not isinstance(body, dict):
        raise ValueError("Expected a JSON object.")
    return body


def _protected_resource(body: dict[str, Any], mcp_url: str, issuer: str) -> None:
    if body.get("resource") != mcp_url:
        raise ValueError("resource does not exactly match --mcp-url; check ICS_MCP_RESOURCE_URI.")
    servers = body.get("authorization_servers")
    issuer_variants = {issuer}
    parts = urlsplit(issuer)
    if parts.path in {"", "/"}:
        # FastMCP's AnyHttpUrl serializes a root issuer with a trailing slash.
        # Only that root-path spelling is interchangeable in this list.
        issuer_variants.update({_url_at(parts, ""), _url_at(parts, "/")})
    if not isinstance(servers, list) or not any(
        isinstance(server, str) and server in issuer_variants for server in servers
    ):
        raise ValueError("authorization_servers does not contain the expected public ICS issuer.")


def _authorization_server(body: dict[str, Any], issuer: str) -> None:
    if body.get("issuer") != issuer:
        raise ValueError("issuer does not match --issuer; check the public ICS URL.")
    for field in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "jwks_uri"):
        value = body.get(field)
        if not isinstance(value, str):
            raise ValueError(f"Missing {field} in authorization-server metadata.")
        try:
            _public_url(value)
        except ValueError:
            raise ValueError(
                f"{field} must be an absolute HTTP(S) URL without credentials."
            ) from None
    for field, required in (
        ("response_types_supported", "code"),
        ("grant_types_supported", "authorization_code"),
        ("grant_types_supported", "refresh_token"),
        ("code_challenge_methods_supported", "S256"),
        ("token_endpoint_auth_methods_supported", "none"),
        ("scopes_supported", "ics"),
    ):
        values = body.get(field)
        if not isinstance(values, list) or required not in values:
            raise ValueError(f"{field} does not advertise {required}.")


def check_remote(client: httpx.Client, *, mcp_url: str, issuer: str) -> list[Check]:
    """Inspect three public endpoints, retaining independent failures.

    Resource and AS issuer identifiers must match exactly. Only a root slash
    added to authorization_servers by FastMCP is tolerated. Discovery paths
    follow RFC 9728 and RFC 8414.
    """
    mcp = _public_url(mcp_url)
    authority = _public_url(issuer)
    resource_metadata = _url_at(mcp, "/.well-known/oauth-protected-resource" + mcp.path)
    server_metadata = _url_at(
        authority, "/.well-known/oauth-authorization-server" + authority.path.rstrip("/")
    )
    health_url = _url_at(mcp, mcp.path.rstrip("/").rsplit("/", 1)[0] + "/health")
    results: list[Check] = []
    for name, url in (
        ("Protected resource metadata", resource_metadata),
        ("Authorization server metadata", server_metadata),
        ("MCP health", health_url),
    ):
        try:
            body = _get_json(client, url)
            if name == "Protected resource metadata":
                _protected_resource(body, mcp_url, issuer)
                message = "resource and authorization_servers match."
            elif name == "Authorization server metadata":
                _authorization_server(body, issuer)
                message = "issuer, OAuth endpoints, DCR, PKCE S256 and scope ics are advertised."
            else:
                if body.get("status") != "ok":
                    raise ValueError("The health response does not report status=ok.")
                message = "The MCP process reports status=ok; this does not test the ICS backend."
        except ValueError as exc:
            results.append(Check(name, False, str(exc), required=name != "MCP health"))
        else:
            results.append(Check(name, True, message, required=name != "MCP health"))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-url", required=True, help="Exact public ICS_MCP_RESOURCE_URI.")
    parser.add_argument("--issuer", required=True, help="Exact public ICS OAuth issuer.")
    parser.add_argument("--timeout", type=float, default=10, help="Timeout per GET, in seconds.")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero.")
    try:
        with httpx.Client(timeout=args.timeout, follow_redirects=False) as client:
            results = check_remote(client, mcp_url=args.mcp_url, issuer=args.issuer)
    except ValueError as exc:
        parser.error(str(exc))
    for result in results:
        status = "PASS" if result.passed else "FAIL" if result.required else "WARN"
        print(f"{status} {result.name}: {result.message}")
    print("Anonymous GET checks only. OAuth login, refresh and tool calls were not tested.")
    return 0 if all(result.passed or not result.required for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
