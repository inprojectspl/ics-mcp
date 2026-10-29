# Connect ChatGPT to ICS

ChatGPT can use the existing remote ics-mcp server to search and read ICS documents, create
Markdown or HTML, and update documents within the connected user's permissions. Each person
connects their own ICS account. The Google Workspace sign-in already used by ICS can remain the
sign-in method; ChatGPT receives an **ICS OAuth token**, not the Google client secret or a shared
administrator token.

This guide covers a custom MCP connection. A public marketplace listing and a custom ChatGPT UI
are not required. The ChatGPT account or workspace must allow custom MCP servers. Interface
labels and availability can change; see OpenAI's
[connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt) and
[OAuth documentation](https://developers.openai.com/plugins/build/auth).

## 1. Operator: prepare the remote endpoint

Use the [deployment guide](https://github.com/inprojectspl/ics-mcp/blob/main/deploy/README.md)
to run ics-mcp with Streamable HTTP behind HTTPS. The URL to add to ChatGPT is the **MCP endpoint**,
for example `https://mcp.ics.example.com/mcp`, not the ICS home page.

These example addresses are placeholders. Use one exact public resource URL throughout the
configuration, including the same path and trailing-slash convention.

| Setting | ICS backend | ics-mcp service |
|---|---|---|
| Public OAuth issuer | `ICS_OAUTH_ISSUER=https://ics.example.com` (or the same public `ICS_BASE_URL` fallback) | `ICS_MCP_OAUTH_ISSUER=https://ics.example.com` |
| MCP resource / token audience | `ICS_MCP_RESOURCE_URI=https://mcp.ics.example.com/mcp` | The exact same `ICS_MCP_RESOURCE_URI` |
| Backend address | `ICS_BASE_URL=https://ics.example.com` | `ICS_BASE_URL=http://backend:8000`, or another address reachable from this service |
| Transport | Not applicable | `ICS_MCP_TRANSPORT=http` |
| Bind address and port | Existing backend configuration | `ICS_MCP_HTTP_HOST=0.0.0.0`, `ICS_MCP_HTTP_PORT=8765` |

The ICS backend also needs its existing OAuth signing key configuration
(`ICS_OAUTH_PRIVATE_KEY_PEM` or `ICS_OAUTH_PRIVATE_KEY_PEM_PATH`, and `ICS_OAUTH_KID`). Keep the
private key in the backend's secret configuration. It is not a credential to paste into ChatGPT.

Route `/mcp` and the MCP host's `/.well-known/oauth-protected-resource/mcp` to ics-mcp.
Exposing `/health` publicly is optional; it can stay on an internal monitoring route.
Keep Streamable HTTP event streams unbuffered. On the **ICS issuer host**, expose
`/.well-known/oauth-authorization-server` as JSON from the ICS backend. A frontend SPA fallback
that returns HTML with status 200 at that address is not OAuth discovery. The older nested
`/api/auth/oauth/.well-known/oauth-authorization-server` endpoint alone is insufficient when
the advertised issuer is `https://ics.example.com`.

Use an ICS version that also preserves the pending MCP authorization request through Google
SSO. Starting with no ICS session must lead from Google sign-in back to the ICS consent screen
and then to ChatGPT. If it ends at the ICS home page, update the ICS login/resume implementation
before completing the rollout. Test this separately from a browser that is already signed in.

### Check discovery before opening ChatGPT

From a checkout of this repository with its dependencies installed:

```sh
uv run python scripts/check_remote.py \
  --mcp-url https://mcp.ics.example.com/mcp \
  --issuer https://ics.example.com
```

The script makes only anonymous GET requests to protected-resource metadata, authorization-server
metadata and `/health`. It checks exact resource/issuer identifiers and the advertised endpoints,
PKCE S256, public-client authentication, refresh grant and `ics` scope. It detects HTML, redirects
and malformed JSON, prints no response bodies, and exits with `0` when discovery passes, `1` for
failed discovery checks or `2` for invalid arguments. An unavailable or failing `/health` produces
a warning without failing discovery: that route may intentionally be private. The script does not
register an OAuth client, sign anyone in, or call tools.
A successful result confirms discovery, not a completed authorization or a working ICS backend.

Expected discovery relationship:

| Endpoint | Required result |
|---|---|
| `https://mcp.ics.example.com/.well-known/oauth-protected-resource/mcp` | `resource` is the exact MCP URL; `authorization_servers` includes `https://ics.example.com`. |
| `https://ics.example.com/.well-known/oauth-authorization-server` | JSON with that exact `issuer`, the ICS authorize/token/register/JWKS URLs, `S256` and scope `ics`. |
| `https://mcp.ics.example.com/health` (optional) | If publicly exposed, JSON with `status: "ok"`; it checks the MCP process, not ICS connectivity. |

Discovery must be reachable without an ICS session cookie or an extra proxy login. The MCP
endpoint itself stays bearer-protected; do not remove its authentication to make discovery pass.

## 2. User: add the custom MCP server

1. Open **Plugins** in the intended ChatGPT account or workspace.
2. Select **+**, then **Add custom MCP server**.
3. Enter a name such as **ICS** and the exact public MCP URL supplied by your operator.
4. Choose OAuth authentication and automatic client registration when available. ICS exposes a
   Dynamic Client Registration (DCR) endpoint; the registered public client uses PKCE and
   `token_endpoint_auth_method=none`. The requested ICS scope is `ics`.
5. Review the connection settings and choose **Create as a plugin**, then complete the connection.
6. Sign in through ICS with your organization's Google Workspace account. Check the user and
   target resource on the ICS consent screen, then approve the requested access.
7. Return to ChatGPT, install or enable the resulting plugin if prompted, and start a new chat.
   Type `@` and select **ICS**.

With DCR, ChatGPT registers its own callback. Do not reuse the local `ics-mcp-stdio` client, the
Google Workspace OAuth client ID/secret, or a callback copied from a Claude setup. If an operator
uses a pre-registered ICS client instead, register the **exact redirect URI shown by the current
ChatGPT connection flow**. A stable callback is only appropriate when the authorization server
supports the issuer-identification requirements described in OpenAI's OAuth documentation.

If the custom-server option is missing or disabled, check the active account/workspace and its
MCP policy. An operator's successful server preflight does not grant a user permission to add a
custom server in ChatGPT.

## 3. Verify account, reading and one write

Start with these requests in the chat where ICS is selected:

1. **Check identity:** "Show the ICS account connected to this chat." The assistant should use
   `ics_whoami`. Verify the returned account before working with organization documents.
2. **Read:** "List my ICS projects, find [a document I can access], and summarize it with its ICS
   link." This exercises listing, searching and reading with your permissions.
3. **Create a disposable note:** "Create a Markdown note titled ChatGPT connection test with the
   text Connection verified. Use organization SSO sharing, not a public link." Inspect the note
   in ICS and verify its content, author and access settings. `org_sso` is organization access,
   not a private-to-author setting.
4. **Update only that note:** ask for a small content change and approve the specific update.
   Check the new version in ICS. Do not test overwrites on an existing team document.

The operator should also verify a second account with fewer permissions, refusal of access to a
known restricted document, and token refresh/reconnection after expiry. Discovery checks alone
do not exercise those paths. The HTTP server uses the incoming user's token for each ICS request;
each additional person must complete their own connection.

## Write confirmations

Keep the server's `ICS_MCP_DEFAULT_CONFIRM=interactive` and `ICS_MCP_ALLOW_YOLO=false` for this
setup. Destructive tools declare `destructiveHint` and use the existing confirmation flow.
Check ChatGPT's confirmation behavior with the disposable note before relying on updates or
deletions in normal work.

If ChatGPT does not support the required MCP elicitation form, the tool returns `confirm_required`
without performing the operation. After the user approves that **specific** action, the client
can retry it with `confirm=true`. That argument overrides the session mode, including `dry_run`;
it is a caller-supplied flag, not server-verifiable proof of a human click. Do not enable session-wide
YOLO mode to work around a missing confirmation UI. If your policy requires a separately enforced
approval, add that enforcement before enabling those operations. See
[Confirmations and safety](confirmations-and-safety.md).

## Text and file limits

| Operation | Remote ChatGPT connection |
|---|---|
| Search/read existing Markdown, HTML, converted PDF and Word documents | Supported through the existing tools, within ICS permissions. |
| Create/update Markdown and HTML bundles | Send content inline; `content_path` is unavailable over HTTP. |
| Upload/replace a PDF or Word/ODF file | The current document tools require local `file_path` and are **stdio only**. Upload through ICS or use a local MCP client, then read it from ChatGPT. |
| Use a ChatGPT sandbox path as an ICS-MCP server path | Unsupported; the two machines do not share a filesystem. |

Direct upload of a PDF/DOCX generated in ChatGPT requires a separate remote file-transfer feature.
This connection guide does not add one. A standard custom MCP connection can use the existing
named tools; the separate ChatGPT Company Knowledge experience has its own `search`/`fetch`
requirements.

## Troubleshooting

| Symptom | Check |
|---|---|
| Preflight finds HTML at authorization-server metadata | Route the issuer's root discovery path to the ICS backend and deploy a version providing that path. |
| Consent opens but Google sign-in loses the connection | Check the ICS OAuth login/resume fix; repeat with no pre-existing ICS browser session. |
| OAuth succeeds but MCP returns `401` | Match the public issuer and exact resource/audience on both services; check the signing key/JWKS and token expiry. |
| `403` with `origin not allowed` | Inspect the actual request Origin. Add `https://chatgpt.com` to `ICS_MCP_EXTRA_ORIGINS` if that is the blocked origin; preserve other required origins. Requests without Origin already pass. Do not use a wildcard. |
| Update/delete returns `confirm_required` | Review and approve the specific action, then use the per-call confirmation flow described above. |
| Upload returns `file_path is only available over stdio` | Use the ICS upload UI or a local MCP client; remote PDF/Word upload is not implemented. |
| Connection works until token expiry | Verify the refresh-token grant with the ChatGPT connection; reconnect if the client cannot refresh. |

## References

- [OpenAI: Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [OpenAI: Authentication](https://developers.openai.com/plugins/build/auth)
- [OpenAI: Build an MCP server](https://developers.openai.com/plugins/build/mcp-server)
- [Remote use over HTTP](remote-http.md)
- [Deployment guide](https://github.com/inprojectspl/ics-mcp/blob/main/deploy/README.md)
