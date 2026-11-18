"""Archive and trash (ICS ADR-0029). An archived asset leaves lists and
search but still opens by slug, link and share; `ics_assets_list` and
`ics_assets_search` browse the archive with `archive`. A deleted asset is in
the trash until it is purged: `ics_trash_list` shows it, `ics_asset_undelete`
brings it back, `ics_asset_purge` deletes it for good."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastmcp import Context, FastMCP
from pydantic import Field

from ics_mcp import models as M
from ics_mcp._helpers import (
    drop_none,
    guarded,
    invalidate_slug_cache,
    map_ics_errors,
    require_uuid,
    resolve_id,
    resolve_id_cached,
)
from ics_mcp._runtime import runtime
from ics_mcp.tools._annotations import DESTRUCTIVE, MUTATING_IDEMP, RO_IDEMP


def _trash_id(asset_id: str) -> None:
    """A deleted asset has no slug lookup: the trash works on ids."""
    require_uuid(
        asset_id,
        code="id_required",
        hint="Take the id from `ics_trash_list` or an earlier output.",
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ics_asset_archive",
        title="Archive or unarchive an asset",
        description=(
            "Moves the asset to the archive of its project (or the global one): lists "
            "and search leave it out unless asked (`archive` in `ics_assets_list` and "
            "`ics_assets_search`), while links, shares and the slug keep working. "
            "`archived=false` brings it back. Owner or project owner. Idempotent "
            "(`noop`)."
        ),
        annotations=MUTATING_IDEMP,
    )
    @map_ics_errors
    async def ics_asset_archive(
        ctx: Context, slug_or_id: str, archived: bool = True
    ) -> dict[str, Any]:
        asset_id = await resolve_id_cached(ctx, slug_or_id)
        ics = runtime.require_ics()
        send = ics.post_json if archived else ics.delete_json
        result: dict[str, Any] = await send(f"/api/assets/{asset_id}/archive")
        return result

    @mcp.tool(
        name="ics_asset_delete",
        title="Move an asset to the trash",
        description=(
            "Moves the asset to the trash: nobody reaches it, its links stop and "
            "per-person shares go. `ics_asset_undelete` brings it back until the "
            "trash purges it (`purge_at` in `ics_trash_list`, 30 days by default). "
            "To keep it but take it off lists, archive it (`ics_asset_archive`)."
        ),
        annotations=DESTRUCTIVE,
    )
    @guarded("delete_asset", target=lambda slug_or_id, **_: slug_or_id)
    @map_ics_errors
    async def ics_asset_delete(
        ctx: Context, slug_or_id: str, confirm: M.ConfirmFlag = None
    ) -> dict[str, Any]:
        asset_id, meta = await resolve_id(slug_or_id)
        await runtime.require_ics().delete_json(f"/api/assets/{asset_id}")
        invalidate_slug_cache(ctx, slug_or_id)
        return {"id": asset_id, "slug": meta["slug"], "deleted": True}

    @mcp.tool(
        name="ics_trash_list",
        title="List the trash",
        description=(
            "Deleted assets the caller may restore or purge (their own and those of "
            "projects they own), most recently deleted first, with `id`, "
            "`deleted_at`, `deleted_by` and `purge_at` (when the purge removes it for "
            "good). `project_id` narrows it to one project's trash. Restore with "
            "`ics_asset_undelete(id)`."
        ),
        annotations=RO_IDEMP,
    )
    @map_ics_errors
    async def ics_trash_list(
        project_id: UUID | None = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict[str, Any]:
        params = drop_none(limit=limit, offset=offset, project_id=project_id and str(project_id))
        page: dict[str, Any] = await runtime.require_ics().get_json(
            "/api/assets/trash", params=params
        )
        return page

    @mcp.tool(
        name="ics_asset_undelete",
        title="Restore an asset from the trash",
        description=(
            "Takes an asset out of the trash. Requires its UUID (from `ics_trash_list`; "
            "slug lookup does not work for deleted assets). Links and per-person shares "
            "are not restored. Its bytes count against the owner's quota again."
        ),
        annotations=MUTATING_IDEMP,
    )
    @map_ics_errors
    async def ics_asset_undelete(asset_id: str) -> dict[str, Any]:
        _trash_id(asset_id)
        result: dict[str, Any] = await runtime.require_ics().post_json(
            f"/api/assets/{asset_id}/undelete"
        )
        return result

    @mcp.tool(
        name="ics_asset_purge",
        title="Delete an asset for good",
        description=(
            "Deletes an asset from the trash for good, with every version and file. "
            "Only an asset already in the trash (`ics_asset_delete` first); the "
            "trash purges it by itself at `purge_at`. Cannot be undone. Needs the "
            "UUID from `ics_trash_list`."
        ),
        annotations=DESTRUCTIVE,
    )
    @guarded("purge_asset", target=lambda asset_id, **_: asset_id)
    @map_ics_errors
    async def ics_asset_purge(
        ctx: Context, asset_id: str, confirm: M.ConfirmFlag = None
    ) -> dict[str, Any]:
        _trash_id(asset_id)
        result: dict[str, Any] = await runtime.require_ics().post_json(
            f"/api/assets/{asset_id}/purge"
        )
        return result
