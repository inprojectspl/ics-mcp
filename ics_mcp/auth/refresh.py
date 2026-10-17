"""Refresh-token grant: hit ICS, rotate stored pair."""

from __future__ import annotations

import time

import httpx

from ics_mcp.auth.token_store import TokenPair, TokenStore
from ics_mcp.config import Settings
from ics_mcp.errors import ICSError


async def refresh_token_grant(
    settings: Settings,
    store: TokenStore,
    current: TokenPair,
    *,
    http: httpx.AsyncClient | None = None,
) -> TokenPair:
    """Refresh token grant. Reuses caller's httpx client (HTTP/2 + pool)
    when available; creates a one-shot otherwise (early-init paths)."""
    owned = http is None
    client = http or httpx.AsyncClient(timeout=15.0)
    try:
        resp = await client.post(
            settings.token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": current.refresh_token,
                "client_id": settings.mcp_oauth_client_id,
                "resource": settings.mcp_resource_uri,
            },
        )
    finally:
        if owned:
            await client.aclose()
    if resp.status_code != 200:
        try:
            data = resp.json()
        except ValueError:
            data = {"error": "unknown", "error_description": resp.text}
        raise ICSError(
            "refresh_failed",
            f"ICS rejected refresh: {data.get('error') or resp.status_code}",
            status=resp.status_code,
            data=data,
        )
    body = resp.json()
    new_pair = TokenPair(
        access_token=body["access_token"],
        # Servers that do not rotate refresh tokens omit the field.
        refresh_token=body.get("refresh_token", current.refresh_token),
        expires_at=time.time() + int(body["expires_in"]),
        scope=body.get("scope", current.scope),
        resource=body.get("resource", current.resource),
    )
    store.save(new_pair)
    return new_pair
