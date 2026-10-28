"""Read-side models: identity, session and asset projections."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, Field

from ics_mcp.models.vocab import (
    AssetKind,
    AssetRole,
    ConfirmModeArg,
    Freshness,
    MetadataFlag,
    OfficeSourceFormat,
    ShareMode,
    SummarySource,
)

# ----------------------- common -----------------------


class WhoamiOut(BaseModel):
    user_id: str
    email: str
    display_name: str | None
    role: str
    scopes: list[str]
    client_id: str | None
    transport: str | None
    audience: str | None


class SessionStatusOut(BaseModel):
    mode: ConfirmModeArg
    server_version: str
    protocol_version: str


class HelpOut(BaseModel):
    topic: str
    content_markdown: str


# ----------------------- asset projections -----------------------


def successor_slug(value: Any) -> Any:
    """ICS sends the successor as `{id, slug, title}` in /meta and the reads;
    every MCP output names it by slug, like the graph and the context pack."""
    if isinstance(value, dict):
        return value.get("slug")
    return value


#: Slug of the direct successor of a superseded document.
type SuccessorSlug = Annotated[str | None, BeforeValidator(successor_slug)]


class Maintainer(BaseModel):
    id: UUID
    email: str | None = None
    display_name: str | None = None


OcrStatus = Literal["not_requested", "queued", "running", "done", "failed"]


class OcrState(BaseModel):
    """OCR of a pdf_doc version (ICS ADR-0021): the text of pages without a
    text layer. `not_requested` until a run is queued; `pages_without_text`
    0 means there is nothing to read."""

    status: OcrStatus
    pages_without_text: int
    #: Scans whose text is an invisible layer saved in the file (e.g. by the
    #: scanner), of unknown quality: OCR is recommended; a request replaces it.
    pages_with_hidden_text: int = 0
    #: False when the ICS operator turned OCR off.
    available: bool = True
    provider: str | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    pages_total: int | None = None
    pages_done: int | None = None
    #: Pages where OCR found text (the rest are blank or pictures).
    pages_recognized: int | None = None
    #: Why a `failed` run failed (`ocr_timeout`, `ocr_engine_failed`, ...).
    error_code: str | None = None


class AssetMeta(BaseModel):
    """`/api/assets/index` item and `/by-slug/{slug}/meta` (ICS `AssetIndexItem`).
    The metadata fields default to empty so an older ICS still validates."""

    id: UUID
    slug: str
    title: str | None
    kind: AssetKind
    size_bytes: int | None
    version: int
    updated_at: datetime
    pinned: bool
    owner_id: UUID
    project_id: UUID | None
    tags: list[str]
    has_versions: bool
    access_role: AssetRole
    #: Last content change (a new version); `updated_at` also moves on metadata edits.
    content_updated_at: datetime | None = None
    #: Truncated preview in lists, full text in `ics_asset_meta`.
    summary: str | None = None
    summary_source: SummarySource | None = None
    doc_type: str | None = None
    freshness: Freshness | None = None
    flags: list[MetadataFlag] = Field(default_factory=list)
    maintainer: Maintainer | None = None
    #: Slug of the visible successor when `freshness` is `superseded`.
    superseded_by: SuccessorSlug = None
    #: Slug of the newest visible document of the `supersedes` chain (the
    #: current version) when this one is superseded.
    latest: str | None = None
    #: Size of the document text in tokens, when ICS reports it.
    estimated_tokens: int | None = None
    #: pdf_doc only: OCR of the current version.
    ocr: OcrState | None = None
    # Single-document reads only (`/meta`), so an edit can start from the
    # stored values: `ics_asset_set_meta` writes these.
    summary_version: int | None = None
    maintainer_id: UUID | None = None
    review_due_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by: UUID | None = None
    language: str | None = None
    properties: dict[str, Any] | None = None


class DocTypeOut(BaseModel):
    """One row of `GET /api/doc-types` (ICS `services/doc_types.py::doc_type_row`),
    trimmed to what an agent needs to pick a type."""

    key: str
    #: Label in the caller's ICS locale.
    label: str
    agent_hint: str | None = None
    default_review_days: int | None = None


class DocTypesOut(BaseModel):
    doc_types: list[DocTypeOut]


class AssetReadOut(BaseModel):
    """Text (`content` plus line range) or a binary bundle file
    (`content_base64` plus `mime`/`size_bytes`, `encoding="base64"`)."""

    slug: str
    path: str
    #: Set when the document is superseded: tells the agent to prefer the successor.
    #: Declared before `content` so it precedes the content in the serialized output.
    notice: str | None = None
    freshness: Freshness | None = None
    superseded_by: SuccessorSlug = None
    #: Slug at the end of the `supersedes` chain: the version to read instead.
    latest: str | None = None
    content: str | None = None
    total_lines: int | None = None
    returned_range: list[int] | None = None
    #: `max_lines` without `lines`: true when the file has more lines.
    truncated: bool | None = None
    content_base64: str | None = None
    mime: str | None = None
    size_bytes: int | None = None
    encoding: str | None = None
    format: str | None = None
    #: Version the content comes from: echo of `?version=` or the current one.
    version: int | None = None
    #: Current asset version. Together with `version` it answers "is this an
    #: archived version?" without an extra `ics_asset_versions` call.
    current_version: int | None = None
    #: pdf_doc only: page count of the PDF whose extracted text is `content`.
    page_count: int | None = None
    #: pdf_doc only: pages with a text layer, and pages whose text came from OCR.
    text_page_count: int | None = None
    ocr_page_count: int | None = None
    #: pdf_doc only: OCR of this version; see `ocr_notice` for what it means here.
    ocr: OcrState | None = None
    #: pdf_doc only: set when pages have no text yet (OCR queued, running,
    #: failed or never requested), so an empty page is not taken as blank.
    ocr_notice: str | None = None
    #: office_doc only: detected format of the uploaded document.
    source_format: OfficeSourceFormat | None = None
    #: office_doc only: number of images, each shown as `[image]` in `content`.
    images: int | None = None


class AssetFileEntry(BaseModel):
    path: str
    size_bytes: int


class AssetFilesOut(BaseModel):
    slug: str
    kind: AssetKind
    version: int
    current_version: int | None = None
    entry_path: str | None
    files: list[AssetFileEntry]


class ResolvedShare(BaseModel):
    mode: ShareMode
    expires_at: datetime | None
    view_count: int
    max_views: int | None


class ResolvedAsset(BaseModel):
    id: UUID
    slug: str
    title: str | None
    kind: AssetKind
    version: int
    entry_path: str | None
    size_bytes: int | None
    security_status: str
    created_at: datetime
    updated_at: datetime


class ShareResolveOut(BaseModel):
    """Response of `POST /api/share/{token}/resolve`: `content` is raw
    markdown (without HTML comments for `format=markdown`); `tree` only for md_collection, `files` only for html_bundle."""

    share: ResolvedShare
    asset: ResolvedAsset
    path: str | None
    content: str | None
    total_lines: int | None = None
    returned_range: list[int] | None = None
    tree: list[str] | None
    files: list[str] | None
    #: pdf_doc only: OCR of the version whose text is `content`.
    ocr: OcrState | None = None
