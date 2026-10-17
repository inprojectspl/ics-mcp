"""Document writes: upload a PDF or a Word/ODF text document as a new asset,
or as the next version of one. The kind (`pdf_doc`, `office_doc`) follows
from the file, so one tool per operation covers both."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from ics_mcp import models as M
from ics_mcp._helpers import guarded, map_ics_errors
from ics_mcp.tools._annotations import DESTRUCTIVE, MUTATING
from ics_mcp.tools._local_document import (
    spec_for_file,
    upload_document_version,
    upload_new_document,
)
from ics_mcp.tools._public_create import confirm_public_create, output_or_preview
from ics_mcp.tools.write_office import OFFICE, OFFICE_HINTS
from ics_mcp.tools.write_pdf import PDF, PDF_HINTS

SPECS = (PDF, OFFICE)
DOCUMENT_HINTS = {**PDF_HINTS, **OFFICE_HINTS}


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ics_asset_create_document",
        title="Upload a PDF or Word/ODF document",
        description=(
            "New asset from a document on the user's machine (`file_path`, stdio "
            "only): `.pdf` becomes `pdf_doc`, `.docx`/`.odt`/`.doc` becomes "
            "`office_doc`. ICS converts it to text, so it is then readable with "
            "`ics_asset_read` and findable with `ics_assets_search`. Returns `kind`, "
            "slug, `share_url` (in `share_mode`, default org_sso; null when held for "
            "review), `security_status` (`critical` blocks sharing until an admin "
            "approves) and `page_count` (PDF) or `source_format` and `images` "
            "(Word/ODF). The title defaults to the file name. Password protected "
            "files are rejected; scanned PDF pages get their text from OCR "
            "(`ics_asset_ocr`), images in Word/ODF documents are not read. "
            '`share_mode="public"` follows the session mode and `confirm` '
            "(dry_run previews it)."
        ),
        annotations=MUTATING,
        output_schema=output_or_preview(M.CreateDocumentOut),
    )
    @map_ics_errors(hints=DOCUMENT_HINTS)
    async def ics_asset_create_document(
        ctx: Context, payload: M.CreateDocumentIn, confirm: M.ConfirmFlag = None
    ) -> M.CreateDocumentOut | dict[str, Any]:
        spec = spec_for_file(SPECS, payload.file_path)
        preview = await confirm_public_create(
            ctx,
            payload.share_mode,
            target=f"new document {payload.title or payload.file_path!r}",
            confirm=confirm,
        )
        if preview is not None:
            return preview
        result = await upload_new_document(ctx, spec, payload)
        return M.CreateDocumentOut(**{**result, "kind": spec.kind})

    @mcp.tool(
        name="ics_asset_replace_document",
        title="Replace a PDF or Word/ODF document (new version)",
        description=(
            "Uploads a local file (`file_path`, stdio only) as the next version of "
            "a `pdf_doc` (a `.pdf`) or `office_doc` (`.docx`/`.odt`/`.doc`, the "
            "format may change) asset. ICS converts and rescans it. History is "
            "kept: reversible via `ics_asset_restore_version`. Other kinds: "
            "`ics_asset_new_version` or `ics_asset_html_replace_bundle`."
        ),
        annotations=DESTRUCTIVE,
    )
    @guarded(
        "replace_document",
        target=lambda slug_or_id, file_path, **_: f"{slug_or_id} <- {file_path}",
    )
    @map_ics_errors(hints=DOCUMENT_HINTS)
    async def ics_asset_replace_document(
        ctx: Context,
        slug_or_id: str,
        file_path: str,
        confirm: M.ConfirmFlag = None,
    ) -> dict[str, Any]:
        return await upload_document_version(ctx, SPECS, slug_or_id=slug_or_id, file_path=file_path)
