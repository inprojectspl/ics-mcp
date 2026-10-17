"""HTML bundle writes. ICS rejects per-file edits of an `html_bundle`, so the
only way to change one is to replace the whole file set as a new version
(`ics_asset_html_replace_bundle`)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from ics_mcp import models as M
from ics_mcp._helpers import (
    guarded,
    invalidate_slug_cache,
    map_ics_errors,
    resolve_id,
    resolve_slug,
)
from ics_mcp._runtime import runtime
from ics_mcp._uploads import resolve_html_file_for_json, upload_files
from ics_mcp.progress import progress_scope
from ics_mcp.tools._annotations import DESTRUCTIVE, MUTATING, RO_IDEMP
from ics_mcp.tools._metadata import METADATA_HINTS, create_metadata_fields
from ics_mcp.tools._public_create import confirm_public_create, output_or_preview


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ics_asset_create_html",
        title="Create an HTML bundle",
        description=(
            "Uploads generated HTML plus assets (CSS/JS/images) as a bundle "
            "with an isolated view. `entry_path` is the start page.\n\n"
            "Each file gives its content through **exactly one** of three fields:\n"
            "- `content_path`: local path on the user's machine (recommended "
            "for files over a few KB, e.g. generated HTML, images). "
            "The MCP server reads the file from disk itself.\n"
            "- `content_text`: short inline text (for snippets under a few KB).\n"
            "- `content_base64`: inline binary (when there is no file on disk).\n\n"
            '`share_mode="public"` follows the session mode and `confirm` '
            "(dry_run previews it)."
        ),
        annotations=MUTATING,
        output_schema=output_or_preview(M.HtmlBundleOut),
    )
    @map_ics_errors(hints=METADATA_HINTS)
    async def ics_asset_create_html(
        ctx: Context, payload: M.CreateHtmlIn, confirm: M.ConfirmFlag = None
    ) -> M.HtmlBundleOut | dict[str, Any]:
        preview = await confirm_public_create(
            ctx, payload.share_mode, target=f"new bundle {payload.title!r}", confirm=confirm
        )
        if preview is not None:
            return preview
        files = payload.files
        async with progress_scope(ctx, total=len(files) + 1, message="Upload HTML") as tick:
            encoded = []
            for f in files:
                encoded.append(resolve_html_file_for_json(f))
                await tick(1, f"+{f.path}")
            body = {
                "title": payload.title,
                "entry_path": payload.entry_path,
                "share_mode": payload.share_mode,
                "project_id": str(payload.project_id) if payload.project_id else None,
                "tags": payload.tags,
                "files": encoded,
                **create_metadata_fields(payload.doc_type, payload.summary),
            }
            result = await runtime.require_ics().post_json("/api/assets/html-json", body)
            await tick(1, "uploaded")
        return M.HtmlBundleOut(**result)

    @mcp.tool(
        name="ics_asset_html_replace_bundle",
        title="Replace the whole HTML bundle (new version)",
        description=(
            "Creates a new version with an entirely new file set. **The only** "
            "way to modify an existing bundle: ICS deliberately does not support "
            "per-file update/add (security model: a bundle is an atomic deploy). "
            "Reversible via `ics_asset_restore_version`.\n\n"
            "Each file: exactly one of `content_path` (recommended over a few KB), "
            "`content_text` or `content_base64`."
        ),
        annotations=DESTRUCTIVE,
    )
    @guarded("html_replace_bundle", target=lambda slug_or_id, **_: slug_or_id)
    @map_ics_errors
    async def ics_asset_html_replace_bundle(
        ctx: Context,
        slug_or_id: str,
        entry_path: str,
        files: list[M.HtmlFile],
        confirm: M.ConfirmFlag = None,
    ) -> dict[str, Any]:
        asset_id, _ = await resolve_id(slug_or_id)

        async def send(mp: list[Any], paths: list[str]) -> dict[str, Any]:
            return await runtime.require_ics().post_multipart(
                f"/api/assets/{asset_id}/versions",
                files=mp,
                data={"entry_path": entry_path, "paths": paths},
            )

        result = await upload_files(
            ctx, files, send, default_mime="application/octet-stream", message="Replace bundle"
        )
        invalidate_slug_cache(ctx, slug_or_id)
        return result

    @mcp.tool(
        name="ics_asset_html_security_review",
        title="HTML bundle security report",
        description="Scan status (clean/warn/critical) plus threat details.",
        annotations=RO_IDEMP,
    )
    @map_ics_errors
    async def ics_asset_html_security_review(slug_or_id: str) -> M.SecurityReviewOut:
        slug = await resolve_slug(slug_or_id)
        data = await runtime.require_ics().get_json(f"/api/assets/by-slug/{slug}/security")
        return M.SecurityReviewOut(**data)
