# ics-mcp: production deploy

The HTTP transport lets ICS-MCP serve remote MCP clients (claude.ai web,
Cursor, custom integrations) over Streamable HTTP. This directory has
everything you need to bolt it onto the existing ICS compose stack.

## Prerequisites

1. ICS backend with its OAuth 2.1 authorization server configured:
   `ICS_OAUTH_PRIVATE_KEY_PEM` (or `_PATH`), `ICS_OAUTH_KID`, and
   `ICS_MCP_RESOURCE_URI` set to the canonical URL of this MCP endpoint,
   e.g. `https://mcp.ics.example.com/mcp`.
2. A DNS record for `mcp.ics.example.com` pointing at your reverse proxy.
3. A reverse proxy with HTTPS termination (Caddy, Traefik, nginx).

## Configuration

| Variable | Meaning |
|---|---|
| `ICS_BASE_URL` | Address the MCP server uses to reach ICS; can be internal (`http://backend:8000`). JWKS is fetched from here. |
| `ICS_MCP_OAUTH_ISSUER` | Public ICS URL, the `iss` of its tokens. Required when `ICS_BASE_URL` is internal. |
| `ICS_MCP_RESOURCE_URI` | Public URL of `/mcp`; tokens must carry it as `aud`. |
| `ICS_MCP_EXTRA_ORIGINS` | Browser origins allowed besides the server's own (e.g. `https://claude.ai`). |
| `ICS_MCP_STATELESS` | `true` for horizontal scaling (see below). |

## How requests are authenticated

- `POST /mcp` without a valid bearer token answers `401` with
  `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp"`.
- Tokens are ICS-issued JWTs, verified against the ICS JWKS for signature,
  issuer, audience and expiry.
- Every call to ICS carries the caller's own token, so each client acts as
  itself. The server keeps no shared token store in this mode, and
  `content_path` arguments are refused because they would read server files.
- A request with an `Origin` header outside the allow-list gets `403`.

## Add the service

Merge `deploy/compose.yaml` into your production compose file (or pass it
with an extra `-f`). The `mcp` service must share a network with the ICS
backend and one with your reverse proxy (`ICS_EDGE_NETWORK`).

## Caddyfile

See `Caddyfile.example`. Key points:
- `flush_interval -1` so the Streamable HTTP `text/event-stream`
  responses aren't buffered.
- `gzip`/`zstd` compression: outline and index payloads benefit a lot.

## Sanity check

```sh
curl -s https://mcp.ics.example.com/.well-known/oauth-protected-resource/mcp | jq
# Expect: { "resource": ".../mcp", "authorization_servers": ["https://ics.example.com"] }

curl -i https://mcp.ics.example.com/mcp -X POST | grep -i www-authenticate
# Expect: Bearer ... resource_metadata="..."

curl -s https://mcp.ics.example.com/health
# Expect: {"status": "ok", ...}
```

## Scaling

The default is stateful (`ICS_MCP_STATELESS=false`): MCP sessions and the
per-session confirm mode live in process memory. To run more than one
replica, set `ICS_MCP_STATELESS=true`; the confirm mode then falls back to
`ICS_MCP_DEFAULT_CONFIRM` on every request.

## Connecting from claude.ai

Settings, Connectors, Add, then enter `https://mcp.ics.example.com/mcp`.
Claude discovers ICS through the protected-resource metadata and runs the
OAuth flow (dynamic client registration, PKCE, resource indicator) itself.

## Monitoring

`GET /health` returns `{status, version, protocol_version}` and is what the
Dockerfile `HEALTHCHECK` probes. It does not call ICS.
