# Remote use over HTTP

ics-mcp can also run as a shared server that MCP clients reach over the network (the Streamable
HTTP transport). This page explains when that is the right choice and what changes for you
compared with the local setup. Setting up such a server is described in the
[deployment guide](https://github.com/inprojectspl/ics-mcp/blob/main/deploy/README.md).

## Local or remote: which one you need

| | Local (stdio) | Remote (HTTP) |
|---|---|---|
| Where ics-mcp runs | On your computer, started by your MCP client. | On a server, run by your ICS operator. |
| Typical clients | Claude Desktop, Claude Code, Cursor. | Web-based clients such as claude.ai connectors, or any client that connects to an MCP URL. |
| Sign-in | ics-mcp opens your browser; tokens go to your OS keyring. | Your MCP client runs the sign-in itself and keeps the token. |
| Local files | Can upload files from your disk. | Cannot read your disk. |
| Setup on your side | Add a configuration block, have `uv` installed. | Add one URL in your client. |

Use the remote server when your client cannot start local programs (claude.ai on the web, for
example), when you work on a machine where a browser sign-in for a local ics-mcp is not possible,
or when your organization prefers to run one managed server instead of a copy on every laptop.

## Connect a client

You need the server's MCP address from your ICS operator, for example
`https://mcp.ics.example.com/mcp`.

In claude.ai, the deployment guide describes the path: Settings, Connectors, Add, then enter the
address. Other clients that support remote MCP servers have a similar setting.

For ChatGPT, use [Connect ChatGPT to ICS](chatgpt.md), including the operator's discovery checks
and the first read/write test. Google Workspace SSO remains on the ICS side of that connection.

The client then finds out on its own that ICS is the sign-in server and runs the sign-in:

1. Your browser opens the ICS sign-in. Sign in if needed.
2. The ICS consent page asks whether to allow the client to access ICS, and shows "Signed in as"
   with your e-mail, the access requested ("Read, create and change your documents and projects,
   within your permissions") and the "Target resource:" (the server's address).
3. Choose **Allow**.

The application name on the consent page is the name the client registered with ICS, so it
depends on the client. Check the e-mail address and the target resource before you allow.

## What changes for you

### No uploads from your disk

Over HTTP, ics-mcp runs on a server and cannot read files on your computer. The local-path options
are refused:

- `content_path` in the Markdown and HTML tools fails with `invalid_argument` ("content_path is
  only available over stdio."). The assistant has to send the content inline instead, which works
  for text and, base64-encoded, for small binary files in HTML bundles.
- `ics_asset_create_document` and `ics_asset_replace_document` (PDF and Word files) fail the same
  way for `file_path`. Upload such files in the ICS web app; the assistant can read and search
  them afterwards.

### Confirm mode per connection

Confirmations work the same way as locally (see
[Confirmations and safety](confirmations-and-safety.md)), with one difference: the mode you set
with `ics_session_set_mode` is kept in the server's memory for your MCP session. If the operator
runs several server replicas in stateless mode, a mode you set does not carry over to the next
request, and every call uses the server's default mode instead. Ask your operator what the default
is if you plan to rely on `dry_run`.

### Sign-in lives in your client

- ics-mcp stores no tokens in this mode. Every request carries your client's own token, which the
  server checks against ICS (signature, issuer, audience, expiry) before it calls ICS as you.
- When the token expires or is rejected, tools return `auth_required`; your client is expected to
  renew it or ask you to sign in again. If it does not, disconnect and reconnect the connector.
- To sign out, remove or disconnect the connector in your client.

Everything else, from search to sharing and the relation graph, works the same as in the local
setup. See [Everyday tasks](everyday-tasks.md).

## Related

- [Getting started](getting-started.md)
- [Confirmations and safety](confirmations-and-safety.md)
- [Troubleshooting](troubleshooting.md)
- [Deployment guide for operators](https://github.com/inprojectspl/ics-mcp/blob/main/deploy/README.md)
