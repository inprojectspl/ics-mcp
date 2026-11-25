# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Micro-application help: pages may use inline styles, images from any `https:` host (map tiles)
  and `fetch` to the hosts declared in `frontend.connect` (ICS ADR-0034); scripts still come only
  from `public/`.
- Google Sheets links per spreadsheet file (ICS ADR-0033). `ics_sheets_link` takes `mappings`, one per
  collection: one tab, several tabs of one kind of record (a tab per month, state or team, with a
  `key_field` unique across them, `append_to` for new records and an optional `tab_field`), or a list
  the app only reads (every column owned by `sheet`); it states the whole link and takes
  `expected_revision`. `ics_sheets_inspect` lists every tab with its `sheet_id` and headers, suggests
  `groups` of tabs with the same headers, marks `formula` columns and takes a tab by name or id.
  Previews name the `collection`, `tab` and `row` of every change, with values keyed by each
  collection's headers. New hints for `sheet_sync_unsettled`, `key_field_required`,
  `append_tab_required` and `sheet_tab_not_found`; the `micro-applications` help topic explains which
  layout of a file maps to which link. Needs ICS with ADR-0033.

### Security

- `ICS_MCP_MAX_UPLOAD_BYTES` and `ICS_MCP_MAX_UPLOAD_FILES` apply to every write: `ics_asset_create_html`
  and the single-content tools (`ics_asset_create_md`, `ics_asset_update_content`, `ics_asset_add_file`)
  now refuse an oversized upload with `payload_too_large` before sending anything to ICS.
- `ics_asset_outline` always asks ICS, so an outline is not served from the session cache after
  access to the document was taken away. The cache only resolves `anchor` for a read ICS checks anyway.
- A server built for stdio is never served over HTTP with its stored tokens: `build_http_app` refuses
  it, and a tool call arriving over HTTP without bearer auth answers `auth_required` instead of using
  the local credentials.
- Dependencies with published advisories are upgraded: fastmcp 3.4.10, authlib 1.9.1, certifi 2026.10.23,
  dnspython 2.9.0, opentelemetry-api 1.45.1. FastMCP now wraps an argument validation error in its own
  `ValidationError`; the `invalid_argument` mapping unwraps it, so tool errors keep their shape.
- joserfc 1.7.6 replaces 1.7.5 (CVE-2026-119284); the strict runtime dependency audit passes without
  exceptions.
- dnspython 2.9.2 (CVE-2026-128089) and opentelemetry-api 1.45.2 (CVE-2026-126360) replace versions
  with a published advisory.

### Added

- Micro-applications built around a Google spreadsheet, and their sync (ICS ADR-0031):
  `ics_sheets_inspect` reads a spreadsheet with the user's connected Google account (headers,
  proposed field names and types, fill rate, uniqueness, samples), `ics_sheets_link` links an app's
  collection to a tab without any id column in the sheet (rows match by an optional unique
  `key_field` or by content), `ics_sheets_unlink` removes it (asks first), `ics_sheets_status`
  shows the link, the owner's row limit and recent syncs (`check=True` settles an `uncertain` sheet
  write by reading the cells back), `ics_sheets_preview` shows what a sync would change, with
  conflicts keyed for decisions, and `ics_sheets_apply` applies a preview with the user's decisions
  (asks first; after a 503 the same call resumes it). The only browser step is Google's consent:
  errors that need it carry `connect_url`. `ics_sheets_link` turns on automatic sync by default for
  an `owner_account` link: ICS keeps the app and the sheet in step on its own, and conflicts or
  errors (`link.auto_error`) wait for the user. The `micro-applications` help topic explains the
  flow and its retry rules. Needs ICS with Google Sheets links configured. Automatic sync follows
  the app's activity (ICS ADR-0032), `ics_microapp_status` shows who uses an app now
  (`runtime.realtime`, `live_people` in the list), and the help explains live updates and realtime
  channels for app pages.
- Archive and trash (ICS ADR-0029). `ics_asset_archive` (`archived=false` brings a document
  back) takes a document off lists and search while its links keep working; `ics_assets_list`
  and `ics_assets_search` take `archive` (`active` by default, `archived`, `all`) and mark items
  `archived`. `ics_trash_list` shows the trash with `deleted_by` and `purge_at`;
  `ics_asset_purge` deletes from the trash for good (destructive, asks first). Needs ICS with the
  archive and trash.
- `ics_project_create` (name, optional description) creates an ICS project owned by the caller, so an agent
  can set up a project before putting documents in it.
- Micro-applications (ICS `ics.microapp/v1alpha1`, PoC): `ics_microapp_contract` (the build standard
  in sections with one `contract_hash`), `ics_microapp_plan` (checks a complete package and binds it
  to a digest), `ics_microapp_apply` (idempotent, returns a durable `operation_id`),
  `ics_microapp_status`, `ics_microapp_control` (enable, suspend, sleep, restart) and
  `ics_microapp_logs`, `ics_microapp_access` (the app's roles, what each permission unlocks, who
  has what) and `ics_microapp_access_set` (exactly these roles and permissions plus opening the
  app, in one idempotent call), plus the `micro-applications` help topic. `ics_share_create_link`
  takes `app_roles` and `app_permissions`. `ics_asset_read` of an app returns its own view with
  the records first (`app_view`) and honours `lines`/`max_lines`. An asset id given to a read
  tool resolves for any viewer through ICS `/api/assets/by-id/{id}/meta` (an older ICS falls
  back to the editor route). `ics_asset_versions` and `ics_asset_diff` compare an app's package
  versions for its publishers; the diff adds `app_changes` (roles, permissions, endpoints, data)
  and keeps them when a long file list is cut. `ics_microapp_plan` takes `change_note`.
  `ics_asset_read` and `ics_asset_list_files` show a micro-application's package through the
  ICS author route, which only publishers may open; the `ics://asset/<slug>` resource reads the
  app itself. Generic tools that cannot serve an app (outline, rendered read, an earlier
  version without `path`, writes) answer with a hint to the right tool. Needs ICS with
  micro-applications enabled.
- A ChatGPT connection guide covering remote MCP, OAuth discovery, Google Workspace sign-in,
  confirmations and HTTP file-upload limits. `scripts/check_remote.py` checks the public metadata
  and health routes with anonymous GET requests and reports configuration/routing failures.
- `ics_share_resolve` takes `format`; `format="markdown"` there and in `ics_asset_read` reads a Markdown file
  without HTML comments (e.g. transcript timestamps), line numbers unchanged. Needs ICS with the same option;
  an older one rejects `format="markdown"` on a Markdown file.
- Documentation site at <https://inprojectspl.github.io/ics-mcp/>, built with MkDocs from `docs/`.
- Version-producing write tools accept an optional `expected_version` and pass the backend's
  `version_conflict` on without retrying. Without it they behave as before; a conditional write
  needs an ICS with the matching version checks.
- Publication identities for HTML creation and whole-version replacements, supplied and kept by the
  caller and confirmed by a durable ICS receipt with its version. `ics_publication_get` reads the
  original result after a lost acknowledgement; an unknown outcome keeps the identity, and the
  server neither generates keys nor retries a write after a transport or gateway failure.
  `scripts/test-publication-backend.sh` runs the contract against a real ICS backend.
- The user guide covers handing out and running micro-applications, moving a document to a project,
  safe retries with `expected_version` and publication keys, the confirmations of the
  micro-application tools, and the errors of publications and micro-applications.

### Changed

- `ics_asset_delete` moves a document to the trash and `ics_asset_undelete` takes it back out;
  their descriptions point to `ics_trash_list`. Descriptions say "earlier version" instead of
  "archived version", which now means the archive of documents.
- Micro-applications run on short addresses (`https://<8-character name>.<apps host>/`, ICS
  ADR-0028). The help, the guide and the contract fixtures describe them; tools pass `app_url` and
  `app_url_pattern` from ICS unchanged.

- Creating a document with `share_mode="public"` (`ics_asset_create_md`, `ics_asset_create_collection`,
  `ics_asset_create_html`, `ics_asset_create_document`) goes through the same confirmation gate as
  `ics_share_create_link(mode="public")`; the four tools take a `confirm` argument.

### Fixed

- `ics_asset_meta` returns the fields `ics_asset_set_meta` writes (`review_due_at`, `reviewed_at`,
  `reviewed_by`, `maintainer_id`, `language`, `properties`, `summary_version`) instead of dropping
  them.
- `ics_share_resolve` accepts a shared document without a title instead of failing with
  `unexpected_response`.
- `ics_asset_outline` always moves forward: a collection file too large for one response shows
  part of its headings and the next page starts after it, instead of an empty page that offered
  the same offset again.
- `ics_asset_versions` returns a long history in pages (`offset`, `next_offset`, `total`)
  instead of a size stub.
- Several ics-mcp processes on one profile refresh the token once, under a lock file, and a
  process that loses the race keeps the fresh pair instead of deleting it or asking to sign in.
- Each `ICS_MCP_KEYRING_SERVICE` gets its own fallback file (`credentials-<service>.json`), so
  profiles stay apart without an OS keyring.
- The Docker image installs the locked dependencies (`uv sync --frozen`), the same set CI tests.
- Interactive confirmations work again: the elicitation request is a typed form that FastMCP 3.4
  accepts, so `interactive` mode no longer fails as if the client did not support elicitation.

### Security

- HTTP sessions are bound to the user (`sub`) who opened them, and the per-session state
  (outline cache, confirm mode) is keyed by the caller too: another user of the same OAuth
  client can no longer use a known session id.

## [0.1.0] - 2026-10-17

First public release of the ICS MCP server.
