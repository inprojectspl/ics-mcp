"""Shared upload flow for single-file document kinds (`pdf_doc`, `office_doc`).
The file is binary and often several MB, so it is read from a local path
(stdio only), never from tool arguments. Kind-specific ICS error codes
(`invalid_pdf`, `office_encrypted`, ...) get a fix hint (`document_hints`),
because the HTTP status alone does not tell them apart."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastmcp import Context

from ics_mcp import models as M
from ics_mcp._helpers import invalidate_slug_cache, resolve_id
from ics_mcp._runtime import runtime
from ics_mcp._uploads import too_large
from ics_mcp.config import get_settings
from ics_mcp.errors import ICSError
from ics_mcp.progress import progress_scope
from ics_mcp.tools._metadata import METADATA_HINTS, create_metadata_fields
from ics_mcp.tools.write_md import apply_create_steps

# Hints for ICS codes shared by every kind; a spec's own `hints` win.
_COMMON_HINTS: Mapping[str, str] = {
    "storage_quota_exceeded": "The storage quota is used up. Delete old assets or versions first.",
}

# Tool that writes the next version of each kind, for the `wrong_kind` hint.
_REPLACE_TOOL = {
    "md_single": "ics_asset_new_version",
    "md_collection": "ics_asset_new_version",
    "html_bundle": "ics_asset_html_replace_bundle",
    "pdf_doc": "ics_asset_replace_document",
    "office_doc": "ics_asset_replace_document",
}


@dataclass(frozen=True)
class DocumentSpec:
    """What differs between the single-file document kinds."""

    kind: str
    #: Human name used in messages and progress ("PDF", "document").
    label: str
    #: ICS endpoint creating the asset from one multipart field `file`.
    create_endpoint: str
    #: Accepted lowercase extensions mapped to the upload content type.
    mimes: Mapping[str, str]
    #: Cheap client-side content check; ICS stays the authority.
    has_signature: Callable[[bytes], bool]
    #: Message suffix when the check fails, e.g. "no %PDF- signature".
    signature_problem: str
    #: ICS code for a wrong extension / for content that fails the check.
    extension_code: str
    signature_code: str
    #: Fix hints for the ICS codes promoted into the tool error.
    hints: Mapping[str, str]


def read_document(spec: DocumentSpec, file_path: str) -> tuple[str, bytes, str]:
    """`(upload filename, bytes, mime)` of a local file, with friendly errors
    for the mistakes an agent makes most: wrong path, wrong file type, a file
    that only has the right name. The size is checked with stat() first."""
    if get_settings().mcp_transport == "http":
        # Over HTTP the path would be read on the server, not on the caller's
        # machine, which exposes server files (including stored tokens).
        raise ICSError(
            "invalid_argument",
            "file_path is only available over stdio.",
            field="file_path",
            hint=f"Upload the {spec.label} through the ICS web UI.",
        )
    p = Path(file_path).expanduser()
    ext = p.suffix.lower()
    mime = spec.mimes.get(ext)
    if mime is None:
        allowed = ", ".join(spec.mimes)
        raise ICSError(
            spec.extension_code,
            f"file_path must point to a {allowed} file: {file_path}",
            hint=spec.hints[spec.extension_code],
        )
    try:
        if not p.is_file():
            raise ICSError(
                "invalid_argument",
                f"file_path: file does not exist: {file_path}",
                field="file_path",
            )
        if p.stat().st_size > get_settings().mcp_max_upload_bytes:
            too_large(f"file_path {file_path}")
        raw = p.read_bytes()
    except PermissionError:
        raise ICSError(
            "invalid_argument", f"file_path: no read permission: {file_path}", field="file_path"
        ) from None
    except OSError as e:
        raise ICSError(
            "invalid_argument", f"file_path: cannot read ({e}): {file_path}", field="file_path"
        ) from None
    if not spec.has_signature(raw):
        raise ICSError(
            spec.signature_code,
            f"Not a {spec.label} ({spec.signature_problem}): {file_path}",
            hint=spec.hints[spec.signature_code],
        )
    # ICS checks the lowercase extension; keep the stem as the user named it.
    return f"{p.stem}{ext}", raw, mime


def document_hints(spec: DocumentSpec) -> dict[str, str]:
    """Fix hints for the ICS codes the tools of `spec.kind` promote: the
    spec's own first, then the shared and the metadata ones."""
    return {**METADATA_HINTS, **_COMMON_HINTS, **spec.hints}


async def upload_new_document(
    ctx: Context,
    spec: DocumentSpec,
    payload: M.LocalDocumentIn,
) -> dict[str, Any]:
    """Create the asset, then apply `title` and `tags` as follow-up steps
    (ICS takes the title from the file name)."""
    ics = runtime.require_ics()
    # Unlike the markdown uploads, these endpoints take `project_id` itself
    # (query string, like `share_mode`), so no follow-up PATCH.
    params: dict[str, Any] = {}
    if payload.share_mode:
        params["share_mode"] = payload.share_mode
    if payload.project_id:
        params["project_id"] = str(payload.project_id)
    async with progress_scope(ctx, total=2, message=f"Upload {spec.label}") as tick:
        filename, raw, mime = read_document(spec, payload.file_path)
        await tick(1, f"+{filename}")
        meta = create_metadata_fields(payload.doc_type, payload.summary)
        result = await ics.post_multipart(
            spec.create_endpoint,
            files=[("file", (filename, raw, mime))],
            data=meta or None,
            params=params or None,
        )
        await tick(1, "uploaded")
    await apply_create_steps(result, title=payload.title or None, tags=payload.tags)
    return result


def spec_for_file(specs: Sequence[DocumentSpec], file_path: str) -> DocumentSpec:
    """The document kind a local file will become, from its extension."""
    ext = Path(file_path).suffix.lower()
    for spec in specs:
        if ext in spec.mimes:
            return spec
    allowed = ", ".join(ext for spec in specs for ext in spec.mimes)
    raise ICSError(
        "document_file_required",
        f"file_path must point to a {allowed} file: {file_path}",
        hint="Upload a PDF or a Word/ODF text document; convert other formats first.",
    )


async def upload_document_version(
    ctx: Context, specs: Sequence[DocumentSpec], *, slug_or_id: str, file_path: str
) -> dict[str, Any]:
    """Upload the file as the next version of a document asset; the asset's
    kind decides which spec the file must satisfy."""
    asset_id, meta = await resolve_id(slug_or_id)
    kind = meta.get("kind")
    by_kind = {spec.kind: spec for spec in specs}
    if kind is None:
        spec = spec_for_file(specs, file_path)
    elif kind in by_kind:
        spec = by_kind[kind]
    else:
        other = _REPLACE_TOOL.get(str(kind))
        raise ICSError(
            "wrong_kind",
            f"{slug_or_id} is a {kind} asset, not a PDF or Word/ODF document.",
            hint=f"Use {other} for {kind} assets." if other else None,
        )
    async with progress_scope(ctx, total=2, message=f"Replace {spec.label}") as tick:
        filename, raw, mime = read_document(spec, file_path)
        await tick(1, f"+{filename}")
        result = await runtime.require_ics().post_multipart(
            f"/api/assets/{asset_id}/versions",
            files=[("files", (filename, raw, mime))],
        )
        await tick(1, "uploaded")
    invalidate_slug_cache(ctx, slug_or_id)
    return result
