# Choosing the right tool

A decision tree for common dilemmas: every pair of tools that can be
confused, with a clear answer on when to use which.

## Searching and listing

| Situation | Tool |
|---|---|
| Find all assets tagged `draft` | `ics_assets_list(tag=["draft"])` |
| Find documents mentioning "Q3" | `ics_assets_list(q="Q3")` |
| Find notes whose content mentions "OKR" | `ics_assets_search(q="OKR")` |
| List everything the user owns | `ics_assets_list(owned=true)` |
| Show files shared with me | `ics_assets_list(shared_with_me=true)` |

**Rule**: use `assets_list` for browsing and metadata filters. Both tools
use the same full-text matching when `q` is supplied. Use `assets_search`
for relevance order and snippets. All query words are required by default;
`match="any"` explicitly broadens search. Use double quotes for a phrase.

## Creating an asset

| What you create | Tool |
|---|---|
| A single MD file | `ics_asset_create_md` |
| An MD vault with `[[wikilink]]` links | `ics_asset_create_collection` |
| An HTML bundle (page with CSS/JS) | `ics_asset_create_html` |
| A PDF or Word/ODF document (.pdf, .docx, .odt, .doc) from the user's disk | `ics_asset_create_document(file_path=...)` |

## Updating an existing asset

| Situation | Tool |
|---|---|
| `md_single`: overwrite the whole file | `ics_asset_update_content` (no `path`) |
| `md_collection`: overwrite one file in the vault | `ics_asset_update_content` with `path="..."` |
| `md_collection`: replace many files at once | `ics_asset_new_version` (atomic, 1 version instead of N) |
| `md_collection`: add a new file | `ics_asset_add_file` |
| `md_collection`: move a file | `ics_asset_move_file` |
| `md_collection`: delete a file | `ics_asset_delete_file` |
| `html_bundle`: any modification | `ics_asset_html_replace_bundle` (the only way; bundles are atomic) |
| `pdf_doc` / `office_doc`: a new file | `ics_asset_replace_document(file_path=...)` (not editable in place) |
| Roll back to an old version | `ics_asset_restore_version` |
| `pdf_doc` scan without text: check or retry OCR | `ics_asset_ocr` (`request=True` to queue it) |

**Rule for collections**: a single file = `update_content`/`add_file`.
Many files at once = `new_version`. Do not push N separate
`update_content` calls in a loop; the backend rate-limits destructive calls.

**Rule for html_bundle**: ICS deliberately blocks per-file edits
(security: atomic deploy). Every change = a new complete version via
`html_replace_bundle`.

## Sharing

| Situation | Tool |
|---|---|
| Paste a link into Slack for the team | `ics_share_create_link(mode="org_sso")` |
| A public link for anyone | `ics_share_create_link(mode="public")` |
| A password-protected link | `ics_share_create_link(mode="password", password="...")` |
| A link for an email allowlist + magic link | `ics_share_create_link(mode="magic_email", allowed_emails=[...])` |
| Lasting access for 1 known user | `ics_share_grant_user(email=..., role=...)` |
| The user pasted a `https://.../s/<token>` link | `ics_share_resolve(share_link=...)` (+ `password` when protected) |

**Rule**: a token link = "paste it somewhere". A per-user grant = "user X
should see it in their UI permanently".

## Reading

| Situation | Tool |
|---|---|
| File listing + meta | `ics_asset_meta` |
| Structure of headings / files (no content) | `ics_asset_outline` |
| Raw markdown | `ics_asset_read` |
| Page content of an `html_bundle` (text/tables) | `ics_asset_read(format="markdown")` |
| Markdown without HTML comments (e.g. transcript timestamps) | `ics_asset_read(format="markdown")` |
| A file from an `html_bundle` (source for editing) | `ics_asset_list_files` → `ics_asset_read(path=...)` |
| Rendered HTML | `ics_asset_read_rendered` (expensive; prefer `read`) |
| Version history (who, when) | `ics_asset_versions` |
| Diff between versions | `ics_asset_diff(v1=, v2=)`: without `path` a list of changes, with `path` the content (also for added/deleted files) |
| Read the content of an old version (without changing the current one) | `ics_asset_read(version=)` |
| What an old version of the asset contained | `ics_asset_list_files(version=)` |

The outline describes only the current version: for an old one use
`ics_asset_list_files(version=)`, then `ics_asset_read(version=, lines=)`.

**Rule**: up to 800 `estimated_tokens`, or when you need most of it, read
the whole document with `ics_asset_read`; otherwise `ics_asset_outline` (no
`edges`), then `ics_asset_read(anchor=...)` or `lines="N-M"` for the sections
you need.

## Tasks and their documents

| Situation | Tool |
|---|---|
| Start work on a task: which documents matter | `ics_task_context(wp=..., ancestors=[...], project=...)` |
| A document is input for a task | `ics_task_link(role="context")` (`required=true` if mandatory) |
| The task produced a document | `ics_task_link(role="deliverable")` |
| Which tasks use this document | `ics_asset_external_refs` |
| Remove a wrong link | `ics_task_unlink(ref_id=...)` |
| Which OP projects and key documents an ICS project has | `ics_project_links(project_slug=...)` |
| Map an OP project, set key documents | `ics_project_links_set(set_external=..., key_documents=...)` |
| How two documents relate to each other | `ics_relation_add` (a document to document edge, not a task link) |

**Rule**: `ics_task_context` first, one call instead of walking links,
relations and metadata yourself. Details: `ics_help('task-context')`.

## Document graph

| Situation | Tool |
|---|---|
| What is around this document (basis, dependencies, successors) | `ics_graph_neighbourhood(slug_or_id=...)` (strong types, depth 1) |
| Which documents this one links to in its content, or which link to it | `ics_graph_neighbourhood(types=["references"])` or `ics_asset_relations(types=["references"])` |
| A document links to others in its text but shows no `references` | `ics_asset_rescan_relations(slug_or_id=...)` once (needs editor); links to documents you cannot open never show |
| The current version of a superseded document | `latest` in `ics_asset_meta`, `ics_assets_list` or `ics_asset_read` (one call) |
| The whole `supersedes` chain | `ics_graph_neighbourhood(types=["supersedes"], depth=3)` (depth 1 is only the next step) |
| The edges of one document with ids (to update or remove one) | `ics_asset_relations(slug_or_id=...)` |
| One chain in one direction (e.g. `derived_from` up to the root) | `ics_graph_neighbourhood(types=[...], direction="out", depth=3)` |
| An edge points at a heading (`target_anchor`) | `ics_asset_read(slug_or_id=<target>, anchor=<target_anchor>)` |
| Record how two documents relate | `ics_relation_add` (follows the confirm gate) |
| Remove a wrong edge | `ics_relation_remove(relation_id=...)` |

**Rule**: decide from node metadata before opening anything, and stop
when the task has what it needs. Details: `ics_help('graph')`.

## Content: inline vs local path

The file fields (`content`/`content_text`/`content_base64`/`content_path`)
are **mutually exclusive**: exactly one per file. Rule of thumb:

- `content` / `content_text`: short inline text (< a few KB).
- `content_base64`: inline binary (when you have no file on disk).
- `content_path`: a local path (`~` expands to home). **Always prefer it
  when you have the file on disk**, whatever its size: it keeps the model's
  context lean, and MCP reads from disk.

Pydantic rejects the payload if you pass 0 or 2+ content_* fields.
