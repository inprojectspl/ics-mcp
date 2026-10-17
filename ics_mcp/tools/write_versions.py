"""Version writes: new_version and restore."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from ics_mcp import models as M
from ics_mcp._helpers import guarded, invalidate_slug_cache, map_ics_errors, resolve_id
from ics_mcp._runtime import runtime
from ics_mcp._uploads import upload_files
from ics_mcp.tools._annotations import DESTRUCTIVE


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ics_asset_new_version",
        title="Upload a new version",
        description=(
            "Saves a **new version of the whole asset**, replacing the previous one. "
            "History is kept: reversible via "
            "`ics_asset_restore_version`.\n\n"
            "For `md_single`: `files` has 1 element, `entry_path` is ignored. "
            "For `md_collection`: `files` contains **all** files of the vault "
            "(they replace the complete set, no merge), `entry_path` is optional.\n\n"
            "When to use: you change many files of an `md_collection` "
            "at once (1 version instead of N separate `update_content` calls), or "
            "you want an atomic swap of the whole file set.\n\n"
            "When not to use: for a single edit of one file in a "
            "collection, `ics_asset_update_content(path=...)` is enough "
            "(cheaper, fewer arguments). For `html_bundle` use "
            "`ics_asset_html_replace_bundle`, for `pdf_doc` and `office_doc` "
            "`ics_asset_replace_document`."
        ),
        annotations=DESTRUCTIVE,
    )
    @guarded("new_version", target=lambda slug_or_id, **_: str(slug_or_id))
    @map_ics_errors
    async def ics_asset_new_version(
        ctx: Context,
        slug_or_id: str,
        files: list[M.CollectionFile],
        entry_path: str | None = None,
        change_note: M.ChangeNoteArg = None,
        confirm: M.ConfirmFlag = None,
    ) -> dict[str, Any]:
        asset_id, _ = await resolve_id(slug_or_id)

        async def send(mp: list[Any], paths: list[str]) -> dict[str, Any]:
            data: dict[str, Any] = {"paths": paths}
            if entry_path:
                data["entry_path"] = entry_path
            if change_note:
                data["change_note"] = change_note
            return await runtime.require_ics().post_multipart(
                f"/api/assets/{asset_id}/versions", files=mp, data=data
            )

        result = await upload_files(ctx, files, send, message="Uploading version")
        invalidate_slug_cache(ctx, slug_or_id)
        return result

    @mcp.tool(
        name="ics_asset_restore_version",
        title="Restore a version",
        description=(
            "Promotes the given historical version to current. Creates a new "
            "version (history stays safe)."
        ),
        annotations=DESTRUCTIVE,
    )
    @guarded(
        "restore_version",
        target=lambda slug_or_id, version, **_: f"{slug_or_id}@v{version}",
    )
    @map_ics_errors
    async def ics_asset_restore_version(
        ctx: Context, slug_or_id: str, version: int, confirm: M.ConfirmFlag = None
    ) -> dict[str, Any]:
        asset_id, _ = await resolve_id(slug_or_id)
        result = await runtime.require_ics().post_json(
            f"/api/assets/{asset_id}/versions/{version}/restore"
        )
        invalidate_slug_cache(ctx, slug_or_id)
        return result
