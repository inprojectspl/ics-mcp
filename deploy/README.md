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

Run the read-only preflight from the repository checkout:

```sh
uv run python scripts/check_remote.py \
  --mcp-url https://mcp.ics.example.com/mcp \
  --issuer https://ics.example.com
```

It performs three anonymous GET requests: protected-resource metadata, authorization-server
metadata at the public issuer, and MCP health. It detects HTML/redirects, malformed metadata and
issuer/resource mismatches. It does not register an OAuth client, authenticate or call tools.
Exit status is `0` when discovery passes, `1` for failed discovery checks, `2` for invalid arguments.
The health check is optional: a private, unavailable or failing `/health` produces a warning and
does not fail discovery. Public health access is not required for a ChatGPT connection.

In particular, `https://ics.example.com/.well-known/oauth-authorization-server` must return JSON
from ICS, not the frontend's HTML fallback. Exposing only
`/api/auth/oauth/.well-known/oauth-authorization-server` does not satisfy discovery for an issuer
at the domain root. Ensure both the ICS backend version and reverse-proxy routing provide it.

Individual checks:

```sh
curl -s https://mcp.ics.example.com/.well-known/oauth-protected-resource/mcp | jq
# Expect: { "resource": ".../mcp", "authorization_servers": ["https://ics.example.com"] }

curl -s https://ics.example.com/.well-known/oauth-authorization-server | jq
# Expect: { "issuer": "https://ics.example.com", "authorization_endpoint": "...", ... }

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

## Connecting from ChatGPT

Follow [Connect ChatGPT to ICS](../docs/guide/chatgpt.md) for account setup, Google SSO, callback
registration and a read/write verification flow. Add the MCP URL as a custom server with OAuth;
the existing ICS DCR endpoint registers the client. Verify root issuer metadata and resuming the
pending consent request after a fresh Google sign-in before rollout.

Keep `ICS_MCP_DEFAULT_CONFIRM=interactive` and `ICS_MCP_ALLOW_YOLO=false`. Test the client's
confirmation behavior explicitly; missing elicitation support is not a reason to enable YOLO.
If OriginGuard rejects a request with `Origin: https://chatgpt.com`, append that exact origin to
`ICS_MCP_EXTRA_ORIGINS`. Requests without an Origin header already work.

Markdown/HTML content works inline over HTTP. Uploading or replacing PDF/Word documents through
the current `file_path` tools remains stdio-only, as described in the guide.

## Monitoring

`GET /health` returns `{status, version, protocol_version}` and is what the
Dockerfile `HEALTHCHECK` probes. It does not call ICS.
