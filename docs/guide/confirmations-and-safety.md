# Confirmations and safety

Operations that delete or overwrite content in ICS pass through a confirmation gate before they
run. This page lists which operations ask, explains the three confirm modes, and helps you pick
one for interactive work and for unattended agents.

## Which operations ask for confirmation

| Operation | Tool |
|---|---|
| Overwrite a file | `ics_asset_update_content` |
| Replace all files of a document (new version) | `ics_asset_new_version` |
| Replace an HTML bundle | `ics_asset_html_replace_bundle` |
| Replace a PDF or Word document | `ics_asset_replace_document` |
| Make an old version current | `ics_asset_restore_version` |
| Move or rename a file in a collection | `ics_asset_move_file` |
| Delete a file from a collection or bundle | `ics_asset_delete_file` |
| Delete a document (soft delete) | `ics_asset_delete` |
| Create a `public` share link | `ics_share_create_link` with mode `public` |
| Create a document with a `public` link | `ics_asset_create_md`, `ics_asset_create_collection`, `ics_asset_create_html` or `ics_asset_create_document` with `share_mode` `public` |
| Revoke a share link or a user's access | `ics_share_revoke` |
| Add a relation between documents | `ics_relation_add` |
| Remove a relation | `ics_relation_remove` |
| Remove a document's link to a task | `ics_task_unlink` |
| Replace a project's tracker links or key documents | `ics_project_links_set` |

The question names the action and its target, for example the document slug, the file being
moved, or both ends of a relation, so you can tell what you are approving.

Everything else runs without asking. That includes creating documents, adding files to a
collection, renaming, tags, pins and metadata, undeleting, OCR requests, linking a document to a
task, and also:

- creating `org_sso`, `password` and `magic_email` share links,
- creating a document with its first share link set to `org_sso`,
- granting a person viewer or editor access, which for an unknown e-mail address creates an
  invited account and sends an invitation.

Most MCP clients also ask you to approve tool calls on their own. Keep that approval on for these
tools if you want a second check.

## The three confirm modes

The session's confirm mode decides what the gate does:

| Mode | What happens on a gated operation | Use it for |
|---|---|---|
| `interactive` (default) | Your MCP client shows a question ("Confirm: ...") and the operation runs only if you accept. | Everyday work with an assistant. |
| `dry_run` | Nothing is sent to ICS. The tool returns a preview with the action, the target and the note "dry_run mode: the operation was not executed." | Checking what a batch of changes would do before running it. |
| `yolo` | No questions; everything runs. | Scripted or scheduled agents that nobody watches. Disabled unless the operator allows it. |

You can ask the assistant to switch: "Switch ICS to dry run" calls `ics_session_set_mode`. "What
ICS mode are we in?" calls `ics_session_status`, which returns the mode.

> [!WARNING]
> A mode lasts until the end of the MCP session, that is until the client disconnects (for a
> local setup, usually until you quit the client) or until it is changed again. After a dry run or
> an unattended batch, switch back to `interactive`.

### When your client cannot ask

Asking works through MCP elicitation, a feature some MCP clients support and others do not. If
yours does not, a gated operation in `interactive` mode fails with `confirm_required` and a hint.
The assistant should then ask you in the chat and, once you agree, repeat the call with
`confirm=true` for that one operation. That keeps the rest of the session safe; avoid switching
the whole session to `yolo` just because your client cannot show the question.

### The per-call `confirm` argument

Every gated tool has an optional `confirm` argument that overrides the session mode for one call:

| `confirm` | Effect |
|---|---|
| `true` | Runs without asking, in every mode. |
| `false` | Refuses, in every mode, with `confirm_required`. |
| not given | Follows the session mode. |

The assistant sets this argument, not you. In practice the gate protects you from accidental
operations and lets you review them, but an assistant that decides to pass `confirm=true` skips
the question. If you want every destructive call reviewed, keep your MCP client's own tool
approval on for the gated tools listed above.

## Safeguards around `yolo`

`yolo` turns off the questions for the whole session, so ics-mcp does not let the assistant turn
it on by itself:

- `ics_session_set_mode("yolo")` works only when whoever configured ics-mcp set
  `ICS_MCP_ALLOW_YOLO=true`, or made `yolo` the starting mode with
  `ICS_MCP_DEFAULT_CONFIRM=yolo`. Otherwise it fails with `yolo_disabled`. An instruction hidden in
  a document therefore cannot switch confirmations off.
- Even in `yolo`, clearing a project's tracker links or key documents with an empty list
  (`ics_project_links_set` with `[]`) is refused unless the call passes `confirm=true`.
- `confirm=false` refuses in `yolo` too.

## How to choose a setup

| Situation | Recommended setting |
|---|---|
| You work with the assistant and watch what it does | Leave the default `interactive`. |
| You want to see what a clean-up would delete before it happens | Ask for `dry_run`, review the previews, then switch back to `interactive` and run it. |
| An unattended agent (CI job, scheduled task) must change documents | Set `ICS_MCP_DEFAULT_CONFIRM=yolo` in that agent's own configuration, ideally with an ICS account that has access only to what the job needs. |
| A client without elicitation, used by a person | Keep `interactive`; the assistant asks in the chat and passes `confirm=true` per call. |

`ICS_MCP_DEFAULT_CONFIRM` sets the mode every new session starts in; it accepts `interactive`,
`yolo` and `dry_run`. Both variables are in the [configuration table](https://github.com/inprojectspl/ics-mcp/blob/main/README.md#configuration).

## Other things that keep your documents safe

- **Changes are reversible.** Every content change creates a new version, and
  `ics_asset_restore_version` brings an old one back. A deleted document can be restored with
  `ics_asset_undelete` (its share links are not restored). Revoking a share is the one gated
  operation that cannot be undone; create a new link instead.
- **The assistant only has your permissions.** See [Overview](overview.md#how-the-assistant-acts-as-you).
  Remember that an ICS administrator account carries administrator reach into the assistant too.
- **Document content is data.** Every read tool reminds the assistant that what it reads is not an
  instruction. Be careful anyway with documents from people you do not know.
- **Rate limits are respected.** When ICS asks to slow down, ics-mcp waits and retries up to three
  times, then returns `rate_limited`. Repeated `rate_limited` errors mean a real limit, not a
  network problem: let the assistant slow down or narrow the work.

## Related

- [Overview](overview.md)
- [Everyday tasks](everyday-tasks.md)
- [Remote use over HTTP](remote-http.md)
- [Troubleshooting](troubleshooting.md)
