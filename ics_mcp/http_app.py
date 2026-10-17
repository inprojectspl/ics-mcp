"""ASGI app for the HTTP transport: the MCP endpoint plus the Origin check the
MCP spec requires against DNS rebinding and cross-site browser calls. Requests
without Origin (CLI, server-side clients) pass; a browser origin must be the
server's own or listed in ICS_MCP_EXTRA_ORIGINS."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send

from ics_mcp.config import Settings


class OriginGuard:
    def __init__(self, app: ASGIApp, allowed: frozenset[str]) -> None:
        self.app = app
        self.allowed = allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            origin = dict(scope.get("headers", [])).get(b"origin")
            if origin is not None and origin.decode("latin-1") not in self.allowed:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"content-type", b"text/plain")],
                    }
                )
                await send({"type": "http.response.body", "body": b"origin not allowed"})
                return
        await self.app(scope, receive, send)


def allowed_origins(settings: Settings) -> frozenset[str]:
    parts = urlsplit(settings.mcp_resource_uri)
    own = f"{parts.scheme}://{parts.netloc}" if parts.netloc else ""
    return frozenset(o for o in (own, *settings.extra_origins_list) if o)


def build_http_app(mcp: FastMCP, settings: Settings):  # type: ignore[no-untyped-def]
    return mcp.http_app(
        path="/mcp",
        middleware=[Middleware(OriginGuard, allowed=allowed_origins(settings))],
        stateless_http=settings.mcp_stateless,
        json_response=settings.mcp_stateless,
    )
