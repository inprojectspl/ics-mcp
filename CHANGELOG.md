# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

### Added

- A ChatGPT connection guide covering remote MCP, OAuth discovery, Google Workspace sign-in,
  confirmations and HTTP file-upload limits. `scripts/check_remote.py` checks the public metadata
  and health routes with anonymous GET requests and reports configuration/routing failures.
- `ics_share_resolve` takes `format`; `format="markdown"` there and in `ics_asset_read` reads a Markdown file
  without HTML comments (e.g. transcript timestamps), line numbers unchanged. Needs ICS with the same option;
  an older one rejects `format="markdown"` on a Markdown file.
- Documentation site at <https://inprojectspl.github.io/ics-mcp/>, built with MkDocs from `docs/`.

### Changed

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
