# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Documentation site at <https://inprojectspl.github.io/ics-mcp/>, built with MkDocs from `docs/`.

### Changed

- Creating a document with `share_mode="public"` (`ics_asset_create_md`, `ics_asset_create_collection`,
  `ics_asset_create_html`, `ics_asset_create_document`) goes through the same confirmation gate as
  `ics_share_create_link(mode="public")`; the four tools take a `confirm` argument.

### Fixed

- Interactive confirmations work again: the elicitation request is a typed form that FastMCP 3.4
  accepts, so `interactive` mode no longer fails as if the client did not support elicitation.

## [0.1.0] - 2026-10-17

First public release of the ICS MCP server.
