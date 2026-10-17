# Security policy

## Supported versions

Security fixes go into the latest release and the default branch. Older
releases do not receive backports.

## Reporting a vulnerability

Please report vulnerabilities privately. Do not open a public issue or pull
request for them. Use
[GitHub private vulnerability reporting](https://github.com/inprojectspl/ics-mcp/security/advisories/new)
(the **Report a vulnerability** button on the repository's Security tab) and
include:

- the affected version or commit,
- how to reproduce the problem (configuration, transport, the tool calls
  involved),
- the impact you expect, for example token disclosure, access beyond the
  signed-in user's permissions, or bypassing the confirmation gate.

We aim to acknowledge a report within a few working days, keep you informed
while we work on a fix, and credit you in the release notes unless you prefer
otherwise. Please give us reasonable time to release a fix before you disclose
the issue publicly.

## Scope

In scope: this repository, that is the MCP server, its OAuth client flow,
token storage and the HTTP transport.

Vulnerabilities in the ICS backend itself belong to the
[ICS project](https://github.com/inprojectspl/ics). If you are not sure which
side is affected, report to the address above and we will route it.
