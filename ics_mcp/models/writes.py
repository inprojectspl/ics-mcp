"""Write-side models: uploads of Markdown, HTML bundles and local documents,
plus task-link inputs."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from ics_mcp.models.assets import OcrState
from ics_mcp.models.vocab import (
    AssetKind,
    DocTypeArg,
    OfficeSourceFormat,
    SummaryArg,
    TagList,
    TaskSystem,
    UploadShareMode,
)


def _normalize_collection_path(p: str) -> str:
    """Mirror of ICS `normalize_collection_path` (`backend/app/collections_io.py`),
    so entry_path comparisons do not depend on how the path was spelled."""
    cleaned = p.replace("\\", "/").lstrip("/")
    parts = PurePosixPath(cleaned).parts
    if not parts or any(part in ("..", "") for part in parts):
        raise ValueError(f"invalid path: {p!r}")
    return "/".join(parts)


# ----------------------- writes: md -----------------------


class CollectionFile(BaseModel):
    path: str
    # Exactly one of: content (inline text), content_path (local path).
    # For files over a few KB use content_path: the MCP server reads the file
    # from disk and keeps the content out of the model context.
    content: str | None = Field(None, max_length=10 * 1024 * 1024)
    content_path: str | None = None

    @model_validator(mode="after")
    def _exactly_one_content(self) -> CollectionFile:
        provided = sum(1 for v in (self.content, self.content_path) if v is not None)
        if provided != 1:
            raise ValueError(
                f"{self.path}: provide exactly one of content/content_path "
                f"(got: {provided}). "
                f"Hint: `content_path='/path/to/file.md'` when the file is "
                f"on disk (preferred), `content='...'` for inline text."
            )
        return self


class CreateMdIn(BaseModel):
    title: str = Field(..., max_length=500)
    # Exactly one of: content (inline text) or content_path (local path).
    # For files over a few KB use content_path.
    content: str | None = None
    content_path: str | None = None
    share_mode: UploadShareMode | None = None
    project_id: UUID | None = None
    tags: TagList = Field(default_factory=list)
    doc_type: DocTypeArg = None
    summary: SummaryArg = None

    @model_validator(mode="after")
    def _exactly_one_content(self) -> CreateMdIn:
        provided = sum(1 for v in (self.content, self.content_path) if v is not None)
        if provided != 1:
            raise ValueError(
                f"provide exactly one of content/content_path "
                f"(got: {provided}). "
                f"Hint: `content_path='/path/to/note.md'` when the file is "
                f"on disk (preferred), `content='...'` for inline text."
            )
        return self


# Out models mirror the JSON of the ICS endpoint named in the docstring; test
# mocks copy that shape from the backend code, since a mock written from the
# model hides drift. Require only what the API guarantees (extras are ignored).


class CreateMdOut(BaseModel):
    """Response of `POST /api/assets` (ICS `routes/assets/crud.py::upload_markdown`)."""

    id: UUID
    slug: str
    title: str | None
    share_url: str | None = None


class CreateCollectionOut(BaseModel):
    """Response of `POST /api/assets/collection`
    (ICS `routes/assets/crud.py::upload_collection`). The backend returns no
    `share_url` even with `share_mode`; read the link via `ics_shares_list`."""

    id: UUID
    slug: str
    title: str | None
    kind: AssetKind
    entry_path: str | None
    file_count: int


class CreateCollectionIn(BaseModel):
    title: str = Field(..., max_length=500)
    files: list[CollectionFile] = Field(..., min_length=1, max_length=500)
    # None lets ICS pick. The tool checks the response, because an older
    # backend silently ignores the field.
    entry_path: str | None = None
    share_mode: UploadShareMode | None = None
    project_id: UUID | None = None
    tags: TagList = Field(default_factory=list)
    doc_type: DocTypeArg = None
    summary: SummaryArg = None

    @model_validator(mode="after")
    def _entry_among_files(self) -> CreateCollectionIn:
        if self.entry_path is not None:
            # Normalize both sides with the same algorithm as ICS
            # (`normalize_collection_path`) and canonicalize the field, so
            # './b.md' matches 'b.md' and the tool's post-condition compares
            # against the form the backend returns.
            entry = _normalize_collection_path(self.entry_path)
            known = {_normalize_collection_path(f.path) for f in self.files}
            if entry not in known:
                raise ValueError(
                    f"entry_path {self.entry_path!r} does not match any "
                    f"of the uploaded files (paths: {sorted(known)[:10]})"
                )
            self.entry_path = entry
        return self


# ----------------------- writes: html bundle -----------------------


class HtmlFile(BaseModel):
    path: str
    # Exactly one of: content_text (short text), content_base64 (binary),
    # content_path (local path). For files over a few KB use content_path:
    # the MCP server reads the file from disk, keeping it out of the model context.
    content_text: str | None = None
    content_base64: str | None = None
    content_path: str | None = None
    mime: str | None = None

    @model_validator(mode="after")
    def _exactly_one_content(self) -> HtmlFile:
        provided = sum(
            1 for v in (self.content_text, self.content_base64, self.content_path) if v is not None
        )
        if provided != 1:
            raise ValueError(
                f"{self.path}: provide exactly one of "
                f"content_text/content_base64/content_path (got: {provided}). "
                f"Hint: `content_path='/path/to/file'` for files on disk "
                f"(preferred, especially for HTML/CSS/JS over a few KB); "
                f"`content_text='...'` for short inline snippets; "
                f"`content_base64='...'` for binary data (images) when there is no file."
            )
        return self


class CreateHtmlIn(BaseModel):
    title: str
    entry_path: str
    files: list[HtmlFile] = Field(..., min_length=1, max_length=50)
    share_mode: UploadShareMode | None = None
    project_id: UUID | None = None
    tags: TagList = Field(default_factory=list)
    doc_type: DocTypeArg = None
    summary: SummaryArg = None


class HtmlBundleOut(BaseModel):
    id: UUID
    slug: str
    title: str | None
    kind: AssetKind
    entry_path: str | None
    file_count: int
    size_bytes: int
    security_status: str


class SecurityReviewOut(BaseModel):
    slug: str
    security_status: str
    security_report: dict[str, Any] | None
    security_bypass: bool
    security_bypass_at: datetime | None
    security_bypass_reason: str | None
    scanned_at: datetime


# ----------------------- writes: pdf, office documents -----------------------


class LocalDocumentIn(BaseModel):
    # Local path on the user's machine (stdio only): the file is binary and
    # often several MB, so it never travels through tool arguments.
    file_path: str
    # ICS derives the title from the file name; a different title is applied
    # by a follow-up PATCH, as for collections.
    title: str | None = Field(None, max_length=500)
    share_mode: UploadShareMode | None = None
    project_id: UUID | None = None
    tags: TagList = Field(default_factory=list)
    doc_type: DocTypeArg = None
    summary: SummaryArg = None


class CreateDocumentIn(LocalDocumentIn):
    pass


class CreateDocumentOut(BaseModel):
    """Response of `POST /api/assets/pdf` or `POST /api/assets/document`, plus
    the `kind` the tool chose from the file."""

    kind: Literal["pdf_doc", "office_doc"]
    id: UUID
    slug: str
    title: str | None
    share_url: str | None = None
    security_status: str
    #: pdf_doc only.
    page_count: int | None = None
    #: pdf_doc only: a scan is queued for OCR at upload (`ocr.status`).
    ocr: OcrState | None = None
    #: office_doc only: format ICS detected from the content.
    source_format: OfficeSourceFormat | None = None
    #: office_doc only: images in the document; the text marks each as `[image]`.
    images: int | None = None


class OcrOut(BaseModel):
    """`ics_asset_ocr`: the OCR state of one pdf_doc version."""

    slug: str
    version: int
    ocr: OcrState
    #: What the state means for reading the document now; absent when done.
    notice: str | None = None


# ----------------------- task links -----------------------


class ProjectExternalRefIn(BaseModel):
    """One entry of `PUT /api/projects/{slug}/external-refs` (ICS ADR-0018)."""

    system: TaskSystem
    external_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=100,
            description="OpenProject project identifier or Project Standard project id.",
        ),
    ]


class KeyDocumentIn(BaseModel):
    """One key document; resolved to `asset_id` for
    `PUT /api/projects/{slug}/key-documents`."""

    slug_or_id: str
    reason: Annotated[
        str | None, Field(max_length=300, description="Why it matters, e.g. 'project charter'.")
    ] = None
