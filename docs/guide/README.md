# ics-mcp user guide

ics-mcp connects an AI assistant (Claude Desktop, Claude Code, Cursor, claude.ai or any other
[MCP](https://modelcontextprotocol.io) client) to [ICS](https://github.com/inprojectspl/ics), the
self-hosted platform your team uses to store and share documents. Once connected, you can ask the
assistant to find, read, write, version and share ICS documents for you, and it does so with your
own ICS account and permissions.

This guide is for people who use ICS through an assistant. If you run ics-mcp for others as a
remote service, also read the [deployment guide](https://github.com/inprojectspl/ics-mcp/blob/main/deploy/README.md). The full list of tools
and configuration variables is in the [project README](https://github.com/inprojectspl/ics-mcp/blob/main/README.md).

## Pages

| Page | What it covers |
|---|---|
| [Overview](overview.md) | What an assistant can do in ICS, how it acts as you, and what it does not do. |
| [Getting started](getting-started.md) | Install, connect your MCP client, sign in for the first time, sign out. |
| [Everyday tasks](everyday-tasks.md) | Worked examples: finding and reading documents, writing and updating, versions, sharing, PDFs and Word files, the relation graph, task context. |
| [Confirmations and safety](confirmations-and-safety.md) | Which operations ask before they run, the three confirm modes and how to choose one. |
| [Remote use over HTTP](remote-http.md) | When ics-mcp runs as a shared server (for example for claude.ai) and what changes for you. |
| [Connect ChatGPT to ICS](chatgpt.md) | Configure a custom MCP connection with Google Workspace sign-in, check discovery, and verify reading and writing. |
| [Troubleshooting](troubleshooting.md) | Error codes you may see, what they mean and how to fix them. |

## Who this is for

- You already have an ICS account and want an assistant to work with your documents: start with
  [Getting started](getting-started.md).
- You want to know what the assistant is allowed to do before you connect it: read the
  [Overview](overview.md) and [Confirmations and safety](confirmations-and-safety.md).
- Your organization offers ics-mcp as a remote connector: go to
  [Remote use over HTTP](remote-http.md).

## Related

- [Overview](overview.md)
- [Getting started](getting-started.md)
- [Troubleshooting](troubleshooting.md)
