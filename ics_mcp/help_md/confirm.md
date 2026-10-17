# Confirm: three modes

Every destructive tool (`delete`, `revoke`, `restore`, `update_content`,
`move_file`, ...) checks the session mode and the `confirm` flag before it runs.
So does publishing to anyone with the URL: `ics_share_create_link(mode="public")`
and every create tool called with `share_mode="public"` (`ics_asset_create_md`,
`_create_collection`, `_create_html`, `_create_document`); the preview action
is `create_public_link`.

> ⚠️ **The session mode lasts until the end of the MCP session**:
> `ics_session_set_mode("yolo")` means **every** later destructive call runs
> without asking, until the MCP client disconnects or you call `set_mode`
> again. If you are not sure what is currently set, call `ics_session_status`;
> it returns a `mode` field.

## `interactive` (default)
If the MCP client supports elicitation (Claude Desktop, Claude.ai web,
newer Claude Code), it shows a modal asking for confirmation.

## `yolo`
No prompts, everything runs. For autonomous agents, runbooks and
scheduled tasks.

```
ics_session_set_mode(mode="yolo")
```

Works only when the server operator set `ICS_MCP_ALLOW_YOLO=true`
(or the default mode `ICS_MCP_DEFAULT_CONFIRM=yolo`). Otherwise `set_mode`
returns `yolo_disabled`; pass `confirm=true` on the call instead.

## `dry_run`
Every destructive tool returns a preview:
```json
{"action":"delete_asset","target":"<slug>","note":"dry_run mode: the operation was not executed."}
```
Nothing is sent to ICS. Ideal for "what would happen if I..." audits.

## Per-call override

Every destructive tool accepts an optional `confirm` argument
(visible in its `inputSchema`):
- `confirm=true`: run without asking (one-off consent).
- `confirm=false`: refuse (returns a `confirm_required` error); it wins over
  **every** mode, including `yolo` and `dry_run`.
- omitted/`null`: honour the session mode.

Precedence: argument > session mode > default `interactive`.

A client without elicitation support (e.g. a headless agent) in
`interactive` mode gets a `confirm_required` error with a hint; in that
case pass `confirm=true` per call instead of switching the whole session
to `yolo`.
