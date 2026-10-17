"""OCR of scanned PDFs (ICS ADR-0021): state and request/retry, plus the
notice `ics_asset_read` attaches to a PDF whose pages have no text yet."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from ics_mcp import models as M
from ics_mcp._helpers import map_ics_errors, resolve_id_cached, resolve_slug
from ics_mcp._runtime import runtime
from ics_mcp.tools._annotations import MUTATING


def ocr_notice(ocr: dict[str, Any] | None) -> str | None:
    """What an OCR state means for reading the document now; None when every
    page has its text (OCR done, or nothing to read)."""
    if not ocr:
        return None
    missing = ocr.get("pages_without_text") or 0
    match ocr.get("status"):
        case "queued" | "running" as status:
            progress = ""
            if status == "running" and ocr.get("pages_total"):
                progress = f" (page {ocr.get('pages_done') or 0} of {ocr['pages_total']})"
            return (
                f"OCR of the {missing} page(s) without a text layer is {status}{progress}: "
                "those pages have no text yet. Do not wait in a loop; read again later, "
                "`ics_asset_ocr` shows the progress."
            )
        case "failed":
            return (
                f"OCR failed ({ocr.get('error_code') or 'unknown'}): {missing} page(s) "
                "have no text. `ics_asset_ocr(request=True)` retries it."
            )
        case "not_requested" if missing:
            if not ocr.get("available", True):
                return f"{missing} page(s) have no text layer and OCR is turned off on this server."
            return (
                f"{missing} page(s) have no text layer (a scan) and OCR was never requested: "
                "`ics_asset_ocr(request=True)` queues it."
            )
        case "not_requested" if hidden := ocr.get("pages_with_hidden_text") or 0:
            return (
                f"{hidden} page(s) are scans whose text layer was saved in the file (e.g. by "
                "the scanner); ICS has not checked its quality, so `content` may hold "
                "misread words. OCR is recommended: `ics_asset_ocr(request=True)` reads the "
                "page images and replaces that layer."
            )
    return None


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ics_asset_ocr",
        title="OCR of a scanned PDF",
        description=(
            "OCR state of a `pdf_doc`: pages without a text layer (a scan) get their "
            "text from OCR, which runs in the background after an upload. `status`: "
            "`not_requested`, `queued`, `running` (`pages_done` of `pages_total`), "
            "`done` (`finished_at`, `pages_recognized`) or `failed` (`error_code`).\n"
            "`pages_with_hidden_text`: scans with a text layer saved in the file (e.g. "
            "by the scanner), unchecked; OCR is recommended there.\n"
            "- `request=True`: queue OCR of the current version, the first run or a "
            "retry after a failure or a poor result; it also replaces saved layers. Refused while a run is active "
            "(`ocr_in_progress`), when every page has text (`ocr_not_needed`) and for "
            "any kind but `pdf_doc` (`ocr_not_supported`: text formats need no OCR).\n"
            "OCR text reads through `ics_asset_read`; each such page is marked "
            "`_Text recognized by OCR._` and may contain recognition errors. Do not "
            "poll in a tight loop: a long scan takes minutes."
        ),
        annotations=MUTATING,
    )
    @map_ics_errors
    async def ics_asset_ocr(ctx: Context, slug_or_id: str, request: bool = False) -> dict[str, Any]:
        ics = runtime.require_ics()
        if request:
            asset_id = await resolve_id_cached(ctx, slug_or_id)
            data = await ics.post_json(f"/api/assets/{asset_id}/ocr")
        else:
            slug = await resolve_slug(slug_or_id)
            data = await ics.get_json(f"/api/assets/by-slug/{slug}/ocr")
        out = M.OcrOut(**{**data, "notice": ocr_notice(data.get("ocr"))})
        return out.model_dump(mode="json", exclude_none=True)
