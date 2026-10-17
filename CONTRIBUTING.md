# Contributing to ics-mcp

Thanks for your interest. This guide covers the local setup, the checks CI
runs and the conventions the code follows.

## Setup

You need Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/inprojectspl/ics-mcp
cd ics-mcp
uv sync --extra dev
```

The tests do not need a running ICS: they mock the ICS API with `respx` and
replace the OS keyring with an in-memory one (autouse fixture in
`tests/conftest.py`).

## Checks

Run what CI runs before you open a pull request:

```bash
uv run ruff check .
uv run ruff format --check .      # CI checks formatting over the whole repo
uv run mypy ics_mcp               # strict mode
uv run pytest --cov=ics_mcp --cov-fail-under=85
```

Useful subsets:

```bash
uv run pytest tests/test_protocol_init.py -v   # MCP conformance checks
scripts/test.sh tests/test_ics_client.py      # same, via the locked dev environment
uv run pytest -k tools
```

## Trying the server against a real ICS

For manual end-to-end testing you need an ICS backend. Run one from the
[ICS project](https://github.com/inprojectspl/ics) following its README, with
`ICS_MCP_RESOURCE_URI` set so that it seeds the `ics-mcp-stdio` OAuth client.
Then point the server at it:

```bash
export ICS_BASE_URL=http://ics.localhost
export ICS_MCP_RESOURCE_URI=http://ics.localhost/mcp
npx @modelcontextprotocol/inspector uv run ics-mcp
```

The first tool call opens the browser for the OAuth login.

## Workflow

1. Branch off the default branch: `feat/<short-description>`,
   `fix/<short-description>`, `docs/...`, `chore/...`.
2. Write the change together with tests.
3. Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
   for commit messages, for example `feat(tools): add ics_asset_set_pin` or
   `fix(auth): handle JWKS rotation race`.
4. Add an entry under `[Unreleased]` in `CHANGELOG.md`
   ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)) for user-visible
   changes.
5. Open a pull request; CI must pass.

## Adding a tool

1. Pydantic input and output models in `ics_mcp/models/`.
2. The implementation in the matching module under `ics_mcp/tools/`
   (`session`, `discovery`, `read`, `write_md`, `write_html`,
   `write_versions`, `share`).
3. Complete annotations from the presets in `tools/_annotations.py`
   (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`);
   `test_all_tools_have_complete_annotations` enforces them.
4. A short, precise English description: when to use the tool, what it does
   not do, and every rule the model must follow.
5. Destructive operations go through the confirm flow (`@guarded` /
   `confirm_or_skip`).
6. Long operations report progress with `progress_scope(ctx, total=...)`.
7. Tests for the happy path and at least one error case; destructive tools
   also need a `dry_run` and a `yolo` test.
8. An entry in `ics_mcp/help_md/tools.md`.

## Conventions

- **English only** in code, comments, docstrings, log messages, tool
  descriptions, help pages and error messages. Tests enforce it for tool
  descriptions, help pages, comments and docstrings.
- **stdout belongs to the protocol** in stdio mode. No `print()` in
  `ics_mcp/`; log with `structlog` (stderr) or `ctx.info()`.
- **Type hints everywhere**; `mypy --strict` must pass.
- **Async everywhere**; do not block the event loop.
- **Errors**: raise `ICSError(code, message, hint=...)`; the client receives
  `isError: true` with structured content. Error codes are stable, messages
  may change.
- **Tokens** never go to logs, traces or error messages.

## Documentation

The site at <https://inprojectspl.github.io/ics-mcp/> is built with
[MkDocs](https://www.mkdocs.org) and [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
from `docs/` and `mkdocs.yml`. The Docs workflow builds it for every pull request that touches
them and publishes it to GitHub Pages from `main`. To preview it locally:

```sh
pip install -r docs/requirements.txt
mkdocs serve
```

`mkdocs build --strict` must pass: a broken link or anchor fails the build. Link to files outside
`docs/` by their full GitHub URL. In a fork, set **Settings > Pages > Source** to
**GitHub Actions** before the first deploy.

## Releases

1. Bump `version` in `ics_mcp/__init__.py` and `pyproject.toml`.
2. Move the `[Unreleased]` entries in `CHANGELOG.md` under the new version.
3. Tag `vX.Y.Z`.
