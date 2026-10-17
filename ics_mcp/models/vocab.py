"""Literal vocabularies and annotated argument types shared by the models
and the tool signatures."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from ics_mcp.config import ConfirmMode

type AssetKind = Literal["md_single", "md_collection", "html_bundle", "pdf_doc", "office_doc"]
#: Format ICS detected from the content of an `office_doc` upload.
type OfficeSourceFormat = Literal["docx", "odt", "doc"]
type ShareMode = Literal["org_sso", "password", "public", "magic_email"]
type UploadShareMode = Literal["org_sso", "public"]
type AssetRole = Literal["owner_file", "project_owner", "editor", "viewer"]
#: Document metadata vocabularies (ICS ADR-0015, `routes/mcp_assets/_models.py`).
type Freshness = Literal["superseded", "review_overdue", "current"]
type SummarySource = Literal["human", "agent"]
type MetadataFlag = Literal["summary_stale", "basis_changed"]
#: Relation graph vocabulary (ICS ADR-0016, `services/relations.py`).
type RelationType = Literal[
    "derived_from",
    "supersedes",
    "depends_on",
    "part_of",
    "references",
    "relates_to",
    "duplicates",
    "contradicts",
]
type RelationDirection = Literal["both", "out", "in"]
#: `compact`: nodes keyed by slug and `[from, type, to]` edges (ICS ADR-0016,
#: section 10); `full`: the verbose ICS shape with ids and every field.
type GraphDetail = Literal["compact", "full"]
#: `ics_assets_list` items: `compact` keeps what picks a document, `full` is
#: the whole ICS row.
type ListDetail = Literal["compact", "full"]
type SearchMatch = Literal["all", "any"]
#: Task links and context packs (ICS ADR-0018, ADR-0019).
type TaskSystem = Literal["openproject", "project_standard"]
type TaskRole = Literal["context", "deliverable", "reference"]
type ContextInclude = Literal["references", "deliverables"]
# Re-export of the canonical mode vocabulary (config.py) under the name used
# in tool signatures: a plain assignment, not a copy of the Literal.
ConfirmModeArg = ConfirmMode

# Per-call `confirm` override: shared annotation for every destructive tool
# (the `guarded` decorator requires the parameter to be present).
# A plain assignment instead of PEP 695 `type`, because the annotation must
# be materialized when FastMCP introspects the signature.
ConfirmFlag = Annotated[
    bool | None,
    Field(
        description="true runs, false refuses; omit to follow the session mode (`ics_help('confirm')`)."
    ),
]

# Tag normalization: mirrors ICS-side `_TAG_RE` + `_MAX_TAGS` from
# `routes/mcp_assets/_shared.py`. Validated locally so the error explaining
# kebab-case reaches the agent before a round trip to ICS.
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}[a-z0-9]$")
_MAX_TAGS = 20


def _validate_tags(v: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tag in v:
        norm = tag.lower().strip()
        if not _TAG_RE.match(norm):
            raise ValueError(f"tag invalid: {tag!r} (kebab-case, 2-32 chars, [a-z0-9_-])")
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    if len(out) > _MAX_TAGS:
        raise ValueError(f"max {_MAX_TAGS} tags per asset")
    return out


type TagList = Annotated[list[str], AfterValidator(_validate_tags)]

# Optional document metadata on create and on new versions (ICS ADR-0015).
# Plain assignments, like ConfirmFlag, so FastMCP sees the Field metadata.
DocTypeArg = Annotated[
    str | None, Field(max_length=32, description="Document type key from `ics_doc_types`.")
]
SummaryArg = Annotated[str | None, Field(description="What the document is for, 1-3 sentences.")]
ChangeNoteArg = Annotated[
    str | None,
    Field(max_length=1000, description="Why this version was made; shown in the history."),
]
