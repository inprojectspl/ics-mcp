## What and why

Short description of the change and the reason for it.

## Checklist

- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy ics_mcp` passes
- [ ] `uv run pytest --cov=ics_mcp --cov-fail-under=85` passes
- [ ] Tests cover the change (destructive tools: `dry_run` and `yolo` cases)
- [ ] Tool descriptions, help pages and messages are in English
- [ ] `CHANGELOG.md` updated under `[Unreleased]` for user-visible changes
- [ ] `ics_mcp/help_md/tools.md` updated if tools changed
