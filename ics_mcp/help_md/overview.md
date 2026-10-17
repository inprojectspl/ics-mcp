# ICS-MCP: Overview

**ICS** (Internal Content Sharing) is a platform for storing and sharing
content inside an organization. An asset is:

- **`md_single`**: a single Markdown file.
- **`md_collection`**: a set of `.md` files linked with `[[wikilink]]`.
- **`html_bundle`**: generated HTML plus assets (e.g. a dashboard, report or
  presentation). Rendered on an isolated subdomain with CSP.
- **`pdf_doc`**: one uploaded PDF. ICS extracts its text (scanned pages
  through OCR), so `ics_asset_read` and `ics_assets_search` work on it like
  on Markdown.
- **`office_doc`**: one uploaded Word/ODF text document (.docx, .odt,
  legacy .doc). ICS converts it to Markdown (headings, lists, tables,
  footnotes; images become `[image]`), read and searched like a PDF.

Every asset:
- belongs to an owner,
- can be in a project (project members inherit access),
- can be shared by link (org_sso/public/password/magic_email) or with a
  specific user from the organization (editor/viewer).

## Where to start

- Working on a task (OpenProject work package or Project Standard node):
  `ics_task_context(wp=..., project=...)` first, one call for the task's
  documents with summary, freshness and size. See `ics_help('task-context')`.
- `ics_assets_list()`: your files, the 20 most recent.
- `ics_assets_search(q="...")`: full-text search with snippets.
- From one document to the related ones: `ics_graph_neighbourhood(slug_or_id=...)`
  (what it was derived from, depends on, replaces or is replaced by); links
  in the content are `references`, followed with `types=["references"]`.
  See `ics_help('graph')`.
- Reading: up to 800 `estimated_tokens`, or when you need most of it, read
  the whole document with `ics_asset_read`; otherwise `ics_asset_outline`
  (no `edges`), then `ics_asset_read(anchor=...)` per section.

For destructive operations (delete, revoke, restore) see `ics_help("confirm")`.
