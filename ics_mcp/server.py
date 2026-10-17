"""FastMCP bootstrap. `build_mcp()` registers tools, resources and prompts,
configures logging, and its lifespan builds the httpx and ICS clients the rest
reaches through `ics_mcp._runtime.runtime`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, RemoteAuthProvider, TokenVerifier
from fastmcp.server.auth.providers.jwt import JWTVerifier
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

from ics_mcp import logging as mcp_logging
from ics_mcp._runtime import runtime
from ics_mcp.auth.token_store import TokenStore
from ics_mcp.config import Settings, get_settings
from ics_mcp.ics_client import ICSClient, build_http_client
from ics_mcp.version import INSTRUCTIONS, PROTOCOL_VERSION, SERVER_INFO


class _SubjectBoundAuth(RemoteAuthProvider):
    """The MCP SDK lets only the principal that opened a session use it,
    comparing client, issuer and subject; FastMCP's JWT verifier leaves
    `subject` empty, so two users of one OAuth client could share a session.
    The token's `sub` fills it in."""

    async def verify_token(self, token: str) -> AccessToken | None:
        access = await super().verify_token(token)
        if access is None or access.subject is not None:
            return access
        sub = (access.claims or {}).get("sub")
        return access.model_copy(update={"subject": str(sub)}) if sub else access


def http_auth(settings: Settings, verifier: TokenVerifier | None = None) -> RemoteAuthProvider:
    """Bearer auth for the HTTP transport.

    Tokens are ICS-issued JWTs whose audience is this MCP server; they are
    checked against the ICS JWKS. Unauthenticated calls get 401 with a
    WWW-Authenticate header pointing at the RFC 9728 metadata, which names
    ICS as the authorization server."""
    if not settings.mcp_resource_uri:
        raise RuntimeError("ICS_MCP_RESOURCE_URI is required for the HTTP transport")
    verifier = verifier or JWTVerifier(
        jwks_uri=settings.jwks_url,
        issuer=settings.issuer,
        audience=settings.mcp_resource_uri,
        algorithm="RS256",
    )
    parts = urlsplit(settings.mcp_resource_uri)
    return _SubjectBoundAuth(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl(settings.issuer)],
        base_url=f"{parts.scheme}://{parts.netloc}",
        resource_name="ICS",
    )


def build_mcp(
    settings: Settings | None = None, *, token_verifier: TokenVerifier | None = None
) -> FastMCP:
    settings = settings or get_settings()
    mcp_logging.configure(settings.mcp_log_level)

    # FastMCP 3.x keeps the lifespan in `_lifespan` (LifespanMixin); `lifespan`
    # is a class method, so assigning it on the instance is a no-op. The
    # lifespan has to be passed as a constructor kwarg.
    @asynccontextmanager
    async def _lifespan(_app: FastMCP) -> AsyncIterator[None]:
        store = TokenStore(
            service=settings.mcp_keyring_service,
            fallback_path=settings.token_fallback_path_resolved,
        )
        http = build_http_client(settings)
        runtime.ics = ICSClient(settings, store, http)
        try:
            yield
        finally:
            await http.aclose()
            runtime.ics = None

    mcp = FastMCP(
        name=SERVER_INFO["name"],
        version=SERVER_INFO["version"],
        instructions=INSTRUCTIONS,
        lifespan=_lifespan,
        auth=http_auth(settings, token_verifier) if settings.mcp_transport == "http" else None,
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "version": SERVER_INFO["version"],
                "protocol_version": PROTOCOL_VERSION,
            }
        )

    from ics_mcp import prompts as prompts_mod
    from ics_mcp import resources as resources_mod
    from ics_mcp import tools as tools_mod

    tools_mod.register_all(mcp)
    resources_mod.register(mcp)
    prompts_mod.register(mcp)
    return mcp


mcp = build_mcp()
