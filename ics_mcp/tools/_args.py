"""Shared tool argument declarations, so an argument's contract is described once
and cannot drift between tools (like `_annotations.py`). The model reads these
descriptions on every call."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

#: `?version=` on the ICS read surfaces.
VersionArg = Annotated[
    int | None,
    Field(
        ge=1,
        description="Archived version to read (from `ics_asset_versions`); omit for the current one.",
    ),
]
