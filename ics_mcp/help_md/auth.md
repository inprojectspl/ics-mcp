# Auth

## First login (stdio)

On the first call of **any** tool, ICS-MCP opens your browser at the ICS
`authorize` URL. After consent, the tokens (an RS256-signed JWT plus a
rotating refresh token) are stored in the **OS keyring**:
- macOS: Keychain (`security` CLI),
- Windows: Credential Manager,
- Linux: libsecret (gnome-keyring / KWallet).

If no keyring is available, it falls back to an encrypted file
`platformdirs.user_data_dir("ics-mcp")/credentials.json` (Fernet, key
derived from the hostname and user id; file mode `0600`).

## Headless / SSH

When there is no `$DISPLAY` or `$BROWSER` and `CI` or
`ICS_MCP_FORCE_HEADLESS` is set, no browser opens and no loopback callback
runs: the tool returns an `auth_required` error with an `authorization_url`
field, and the sign-in cannot finish in that environment. Sign in on a
machine with a browser, or use the HTTP transport.

## Expiry / refresh

The access token lives 1h. The refresh token lives 30 days and **rotates**
(each use invalidates the previous one). Auto-refresh happens on the first
401 from ICS and is invisible to the agent.

## Audience binding (RFC 8707)

The JWT carries `aud == ICS_MCP_RESOURCE_URI`. ICS rejects tokens with a
different audience (anti confused deputy). ICS-MCP **never** passes the token
on to third parties: token passthrough is forbidden by the MCP spec.

## Revocation

Deleting the keyring entry signs this machine out; the refresh token on the
ICS side expires on its own (30 days by default). `ics_whoami()` shows which
token and client the session uses.

## Rate limit (ICS side)

ICS may throttle requests, and the actual limits depend on the instance
configuration. On a 429 the `ics-mcp` client retries at most 3 times, waiting
as long as `Retry-After` says (up to 30 s), so short bursts of traffic need no
special handling by the agent. Once the retries are used up, the tool returns
a `rate_limited` error. **Do not try to work around it**: repeated 429s mean a
real budget, not a network hiccup.

Strategies when you get close to the limit:
- Paginate `ics_assets_list` with `cursor`; do not sweep 10k files per
  minute.
- Filter on the ICS side (`kind=`, `tag=`, `q=`, `project_id=`) instead of
  fetching everything and filtering locally.
- Batch writes: `ics_asset_new_version(files=[...])` instead of N calls to
  `ics_asset_update_content`.
