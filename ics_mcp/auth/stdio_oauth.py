"""OAuth 2.1 loopback login for stdio: PKCE S256 and RFC 8707 resource
indicators, with a one-shot `127.0.0.1` callback server that checks Host and
Origin (DNS-rebinding guard) and the returned `state`. Headless runs get the
authorize URL in an `auth_required` error instead of a browser."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets
import socket
import time
import webbrowser
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode

import httpx

from ics_mcp.auth.callback_page import callback_page
from ics_mcp.auth.token_store import TokenPair, TokenStore
from ics_mcp.config import Settings
from ics_mcp.errors import ICSError
from ics_mcp.logging import get_logger

log = get_logger(__name__)
_FLOW_TIMEOUT_S = 300
_HOSTNAME = "127.0.0.1"


@dataclass
class _CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None
    error_description: str | None = None


def _b64u_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _gen_pkce() -> tuple[str, str]:
    verifier = _b64u_nopad(secrets.token_bytes(64))
    challenge = _b64u_nopad(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _is_headless() -> bool:
    return bool(
        not os.environ.get("DISPLAY")
        and not os.environ.get("BROWSER")
        and (os.environ.get("CI") or os.environ.get("ICS_MCP_FORCE_HEADLESS"))
    )


async def _run_loopback(port: int, expected_state: str) -> _CallbackResult:
    """Single-request HTTP server that captures the callback query string."""
    result = _CallbackResult()
    server_done = asyncio.Event()

    async def _client_connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=10)
            headers: dict[str, str] = {}
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                if line in (b"\r\n", b"\n", b""):
                    break
                if b":" in line:
                    k, _, v = line.decode("latin-1").partition(":")
                    headers[k.strip().lower()] = v.strip()
            # DNS rebinding guard: Host must be loopback, no foreign Origin.
            host = headers.get("host", "")
            if host not in {_HOSTNAME, f"{_HOSTNAME}:{port}"}:
                writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\nbad host")
                await writer.drain()
                return
            origin = headers.get("origin")
            if origin and origin not in {f"http://{_HOSTNAME}:{port}", "null"}:
                writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\nbad origin")
                await writer.drain()
                return
            try:
                method, path, _ = request_line.decode("ascii").split(" ", 2)
            except ValueError:
                writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                await writer.drain()
                return
            if method != "GET" or not path.startswith("/callback"):
                writer.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
                await writer.drain()
                return
            # Only a request to the callback ends the flow; stray requests
            # (favicon, probes) are answered above and the server keeps waiting.
            server_done.set()
            query = path.split("?", 1)[1] if "?" in path else ""
            params = {k: v[0] for k, v in parse_qs(query).items()}
            result.code = params.get("code")
            result.state = params.get("state")
            result.error = params.get("error")
            result.error_description = params.get("error_description")
            html = callback_page(result.error, result.error_description)
            body_bytes = html.encode("utf-8")
            writer.write(
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                f"Cache-Control: no-store\r\n\r\n".encode("ascii")
                + body_bytes
            )
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    server = await asyncio.start_server(_client_connected, _HOSTNAME, port)
    try:
        await asyncio.wait_for(server_done.wait(), timeout=_FLOW_TIMEOUT_S)
    finally:
        server.close()
        await server.wait_closed()

    if result.state != expected_state:
        raise ICSError(
            "state_mismatch",
            "OAuth state token mismatch (possible CSRF)",
            hint="Call the tool again.",
        )
    if result.error:
        raise ICSError(
            "auth_denied",
            result.error_description or result.error,
            hint="The user denied consent in the browser.",
        )
    if not result.code:
        raise ICSError("auth_no_code", "No `code` in the callback")
    return result


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((_HOSTNAME, 0))
        return int(s.getsockname()[1])


def _build_authorize_url(
    settings: Settings, *, redirect_uri: str, state: str, code_challenge: str
) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.mcp_oauth_client_id,
        "redirect_uri": redirect_uri,
        "scope": "ics",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": settings.mcp_resource_uri,
        "state": state,
    }
    return f"{settings.authorize_url}?{urlencode(params)}"


async def login(settings: Settings, store: TokenStore) -> TokenPair:
    """Interactive OAuth login. Headless contexts get a clear error +
    the authorize URL so the user can complete the flow elsewhere."""
    verifier, challenge = _gen_pkce()
    state = secrets.token_urlsafe(24)
    port = _pick_free_port()
    redirect_uri = f"http://{_HOSTNAME}:{port}/callback"
    authorize_url = _build_authorize_url(
        settings, redirect_uri=redirect_uri, state=state, code_challenge=challenge
    )

    if _is_headless():
        raise ICSError(
            "auth_required",
            "No interactive browser; the manual flow is required.",
            hint=(
                "No loopback callback runs in a headless environment, so the "
                "sign-in cannot finish here. Sign in on a machine with a "
                "browser, or run ics-mcp with the HTTP transport."
            ),
            data={"authorization_url": authorize_url},
        )

    callback_task = asyncio.create_task(_run_loopback(port, state))
    try:
        webbrowser.open(authorize_url)
    except Exception as e:
        log.warning("webbrowser.open failed", error=str(e))

    try:
        result = await callback_task
    except TimeoutError as e:
        raise ICSError(
            "auth_timeout",
            "OAuth flow timeout (5 min)",
            hint="Try again; the flow will restart.",
            data={"authorization_url": authorize_url},
        ) from e

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            settings.token_url,
            data={
                "grant_type": "authorization_code",
                "code": result.code,
                "redirect_uri": redirect_uri,
                "client_id": settings.mcp_oauth_client_id,
                "code_verifier": verifier,
                "resource": settings.mcp_resource_uri,
            },
        )
    if resp.status_code != 200:
        body: dict[str, Any]
        try:
            body = resp.json()
        except ValueError:
            body = {"error": "unknown"}
        raise ICSError(
            "token_exchange_failed",
            f"ICS /token returned {resp.status_code}: {body.get('error')}",
            status=resp.status_code,
            data=body,
        )
    body = resp.json()
    pair = TokenPair(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=time.time() + int(body["expires_in"]),
        scope=body.get("scope", "ics"),
        resource=body.get("resource", settings.mcp_resource_uri),
    )
    store.save(pair)
    return pair
