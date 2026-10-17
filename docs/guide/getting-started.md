# Getting started

This page takes you from nothing to a working assistant: add ics-mcp to your MCP client, sign in
to ICS once in the browser, and check that it works. It covers the local (stdio) setup, where
ics-mcp runs on your own computer. For a shared remote server, see
[Remote use over HTTP](remote-http.md).

## Before you start

You need:

- An ICS account and the address of your ICS, for example `https://ics.example.com`.
- An ICS where the administrator has enabled MCP (ICS has `ICS_MCP_RESOURCE_URI` set). If you are
  not sure, ask your ICS administrator for the value of `ICS_MCP_RESOURCE_URI`; you need it below.
- [uv](https://docs.astral.sh/uv/) installed. It provides the `uvx` command that downloads and
  runs ics-mcp.
- An MCP client: Claude Desktop, Claude Code, Cursor, or another client that runs local MCP
  servers.

## Add ics-mcp to your MCP client

All three clients below accept the same configuration block. Replace the two addresses with the
ones of your ICS:

```jsonc
{
  "mcpServers": {
    "ics": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/inprojectspl/ics-mcp", "ics-mcp"],
      "env": {
        "ICS_BASE_URL": "https://ics.example.com",
        "ICS_MCP_RESOURCE_URI": "https://ics.example.com/mcp"
      }
    }
  }
}
```

- `ICS_BASE_URL` is the address of your ICS.
- `ICS_MCP_RESOURCE_URI` must be exactly the value configured in ICS. ICS issues tokens for this
  address and rejects them anywhere else, so a typo here makes sign-in fail.

Where the block goes:

| Client | File |
|---|---|
| Claude Desktop | `claude_desktop_config.json` (open it from Settings, Developer). |
| Claude Code | `.mcp.json` in your project, or add the server with `claude mcp add`. |
| Cursor | `~/.cursor/mcp.json`. |

Restart the client after you edit its configuration.

> [!TIP]
> For a setup that does not change under you, pin a release tag or a commit:
> `git+https://github.com/inprojectspl/ics-mcp@<tag>`.

Other settings (upload limits, the default confirm mode, a different keyring name) are
environment variables too. They are listed in the
[configuration table](https://github.com/inprojectspl/ics-mcp/blob/main/README.md#configuration). Add them to the same `env` block.

If you prefer to run ics-mcp from a local checkout instead of `uvx`, see
"Other ways to install" in the [project README](https://github.com/inprojectspl/ics-mcp/blob/main/README.md#quick-start).

## Sign in for the first time

You do not sign in in advance. The first time the assistant uses an ICS tool, ics-mcp starts the
sign-in for you:

1. Ask the assistant something about ICS, for example "List my ICS documents".
2. ics-mcp opens your browser at the ICS sign-in. If you are not signed in to ICS in this browser
   yet, sign in as usual; ICS then brings you back to the consent page.
3. The consent page asks "Allow MCP stdio (Claude Desktop / Claude Code) to access ICS?" and shows
   "Signed in as" with your e-mail address. Check that it is the account you want the assistant to
   use.
4. Under "The application asks for access on your behalf to:" it lists "Read, create and change
   your documents and projects, within your permissions", and below that the "Target resource:"
   (your `ICS_MCP_RESOURCE_URI`).
5. Choose **Allow**. Choose **Cancel** if you do not recognise the request; nothing is shared then.
6. The browser shows "Signed in to ICS" and "You can close this tab and go back to your MCP
   client." Close the tab.
7. The assistant's original request continues on its own and returns the result.

You have 5 minutes to finish the steps in the browser. After that the attempt expires and the tool
returns `auth_timeout`; ask again and a new attempt starts.

### What is stored, and for how long

- The tokens go to the operating system keyring: the macOS Keychain, the Windows Credential
  Manager, or libsecret on Linux, under the service name `ics-mcp` and the account `default`.
- If no keyring is available, ics-mcp writes them to a `credentials.json` file in its data
  directory, readable only by your user. You can set another location with
  `ICS_MCP_TOKEN_FALLBACK_PATH`.
- With the ICS defaults an access token is valid for one hour and is renewed automatically, so
  you are not asked again. The renewal (refresh) token lasts 30 days and changes on every use. If
  you do not use the assistant for longer than that, you are asked to sign in again.

> [!NOTE]
> Several ics-mcp setups on one computer share one sign-in, because they use the same keyring
> entry. To keep separate sign-ins (for example two ICS instances or two accounts), give each
> setup its own `ICS_MCP_KEYRING_SERVICE`.

## Check that it works

Ask the assistant "Who am I in ICS?". It calls `ics_whoami`, which returns your user id, e-mail,
name, role, the token scope and the OAuth client. The token itself is never shown.

You can also ask "Show the ICS session status". `ics_session_status` returns the current
[confirm mode](confirmations-and-safety.md) and the server and protocol versions.

## Sign in on a machine without a browser

ics-mcp over stdio finishes sign-in through a short-lived listener on `127.0.0.1` of the machine
it runs on, and the browser must be able to reach it. In practice this means the browser has to
run on the same machine as ics-mcp.

When ics-mcp detects that it cannot open a browser (it runs with `CI` or `ICS_MCP_FORCE_HEADLESS`
set and with neither `DISPLAY` nor `BROWSER` set), it does not wait for a browser. The tool returns
`auth_required` with an `authorization_url` instead. In that mode no listener is started, so
opening the URL elsewhere does not complete the sign-in.

For a remote machine or a server without a browser, the reliable options are:

- Run the assistant and ics-mcp on your desktop, where a browser is available.
- Use a shared ics-mcp server over HTTP, where your MCP client runs the sign-in itself. See
  [Remote use over HTTP](remote-http.md).

## Sign out

To make ics-mcp forget your sign-in, delete its keyring entry. The next tool call then starts a
new sign-in.

```bash
# macOS
security delete-generic-password -s ics-mcp -a default
# Linux (libsecret)
secret-tool clear service ics-mcp username default
# Windows
cmdkey /delete:ics-mcp
```

If you set `ICS_MCP_KEYRING_SERVICE`, use that name instead of `ics-mcp`. If your tokens were in
the fallback file (no keyring), delete that `credentials.json` file.

Deleting the entry signs this machine out. The refresh token on the ICS side is not revoked by
this; it expires on its own (30 days by default). If a device with a valid sign-in is lost, ask
your ICS administrator to lock your account: ICS refuses the tokens of a locked account for as
long as the lock lasts.

> [!NOTE]
> The "Access tokens" page in the ICS settings manages personal access tokens, which are a
> separate mechanism. Revoking one there does not affect your ics-mcp sign-in.

## Related

- [Overview](overview.md)
- [Everyday tasks](everyday-tasks.md)
- [Confirmations and safety](confirmations-and-safety.md)
- [Troubleshooting](troubleshooting.md)
