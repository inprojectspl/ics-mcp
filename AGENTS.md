# AGENTS.md

This file is for AI coding agents working on this repository. For end-user
documentation about using `ics-mcp` as an MCP server, start with `README.md`.

## Project

`ics-mcp` is a Python 3.12+ MCP server for ICS (Internal Content Sharing). It
exposes user-level ICS capabilities as MCP tools over `stdio` and Streamable
HTTP.

Primary stack:

- FastMCP 3.3+
- httpx with HTTP/2
- Pydantic v2
- cryptography
- keyring
- structlog

## Working rules

- Keep `mypy --strict` passing.
- Run `ruff check .` and `ruff format --check .` before committing; CI checks
  both over the whole repository.
- Use `pytest` for verification; prefer focused tests matching the surface you
  changed. Tests run against an in-memory keyring (autouse fixture in
  `tests/conftest.py`), never the OS one.
- Do not use `print()` in runtime code. MCP stdio reserves stdout for protocol
  traffic. Log to stderr via structlog or use `ctx.info()`.
- Do not log or expose tokens.
- Write tool, parameter, prompt and resource descriptions, the server
  `INSTRUCTIONS`, `help_md/*.md`, error messages and hints, log messages,
  comments and docstrings in English. `tests/test_english_source.py` enforces
  it. Keep error `code` values stable; messages may change.
- Invalid tool arguments become `invalid_argument` (with `field` and, for
  enums, `data.allowed`) in the `tools/_arg_errors.py` middleware; tools do
  not catch argument `ValidationError`s themselves. A check a tool makes on
  its own arguments (nothing to change, two exclusive arguments, an
  unreadable local file) raises `ICSError("invalid_argument", ..., field=...)`
  too, and an ICS request validation error (`validation_error`, 422) is
  mapped to it in `ics_client.py`. There is no `bad_input`; specific ICS
  codes (`relation_self`, `doc_type_unknown`, ...) stay as they are.

## Repo map

- `ics_mcp/server.py`: FastMCP initialization and lifespan
- `ics_mcp/__main__.py`: stdio vs HTTP entrypoint
- `ics_mcp/config.py`: settings and env config
- `ics_mcp/ics_client.py`: ICS HTTP client and error mapping
- `ics_mcp/models/`: shared Pydantic models and enums (`vocab.py` literals and
  argument types, `assets.py` read models, `writes.py` write models), all
  re-exported from `ics_mcp.models`
- `ics_mcp/_helpers.py`: error mapping, slug/id resolution, confirm guard;
  `_payload.py` response size caps; `_uploads.py` upload file contents
- `ics_mcp/tools/`: MCP tools grouped by domain
- `ics_mcp/resources.py`: MCP resources
- `ics_mcp/prompts.py`: MCP prompts
- `ics_mcp/auth/`: OAuth, token storage, JWT verification, refresh flow
- `tests/`: unit and e2e coverage

## MCP-specific constraints

- Every tool must declare complete MCP annotations. Tests enforce this.
- Destructive operations use confirm flow: `confirm: bool | None = None` plus
  `confirm_or_skip(...)`.
- Resource templates follow RFC 6570.
- Elicitation form schemas must stay flat primitives only.
- Long-running tools should use the progress helpers.

## Change patterns

When adding or changing a tool:

1. Add or update request/response models in `ics_mcp/models/` (and export
   them from `ics_mcp/models/__init__.py`).
2. Implement the tool in the appropriate module under `ics_mcp/tools/`.
3. Use the existing decorators and helper patterns for error mapping and
   destructive-operation guards.
4. Add or update tests in `tests/`.
5. Update help content if user-facing tool behavior changed.

Prefer existing enums and helpers over inline literals or custom ad hoc logic.

## Testing shortcuts

Common commands:

```bash
ruff check .
ruff format --check .
pytest
pytest --cov=ics_mcp --cov-fail-under=85   # the CI coverage gate
pytest tests/test_http_transport.py -v
```

For tool tests, follow existing `respx`-based patterns in `tests/test_tools_e2e.py`
and related modules.

