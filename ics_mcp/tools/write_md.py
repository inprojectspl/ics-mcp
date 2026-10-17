"""Markdown writes: create, rename, content edit, file ops, pin, tags, delete.
The multipart create endpoints take only files and `share_mode`, so title and
project are applied by follow-up calls, each wrapped in `_after_create_step`
so a failure there does not lose the created asset."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any
from uuid import UUID

from fastmcp import Context, FastMCP

from ics_mcp import models as M
from ics_mcp._helpers import (
    guarded,
    invalidate_slug_cache,
    map_ics_errors,
    require_uuid,
    resolve_id,
)
from ics_mcp._runtime import runtime
from ics_mcp._uploads import file_bytes, upload_files
from ics_mcp.errors import ICSError
from ics_mcp.logging import get_logger
from ics_mcp.tools._annotations import (
    DESTRUCTIVE,
    DESTRUCTIVE_IDEMP,
    MUTATING,
    MUTATING_IDEMP,
)
from ics_mcp.tools._metadata import METADATA_HINTS, create_metadata_fields
from ics_mcp.tools._public_create import confirm_public_create, output_or_preview

log = get_logger(__name__)


def _md_filename(title: str | None) -> str:
    """File name from which ICS derives the md_single title
    (`title = filename.removesuffix(".md")`). Not `Path(...).stem`, which would
    turn "v1.2 release notes" into "v1"; separators are replaced because the name
    ends up in the storage key."""
    base = (title or "").removesuffix(".md").replace("/", "-").replace("\\", "-").strip()
    return f"{base or 'index'}.md"


async def _after_create_step(step: Awaitable[Any], *, result: dict[str, Any], action: str) -> None:
    """Guard for follow-up steps after a successful POST (tags, title, project).
    Without it a transient error loses the new id/slug and the agent retries the
    create, making duplicates; the error carries the asset identity instead."""
    try:
        await step
    except ICSError as e:
        raise ICSError(
            e.code,
            f"Asset created (slug={result['slug']}, id={result['id']}), "
            f"but {action} failed: {e.message}",
            hint=e.hint,
            status=e.status,
            data={**e.data, "id": str(result["id"]), "slug": result["slug"]},
        ) from e


async def apply_create_steps(
    result: dict[str, Any],
    *,
    title: str | None,
    tags: list[str],
    project_id: UUID | None = None,
) -> None:
    """Apply what the create endpoint did not take: a title it did not derive
    from the file name, tags and the project. Updates `result["title"]`."""
    ics = runtime.require_ics()
    if title is not None and result.get("title") != title:
        await _after_create_step(
            ics.patch_json(f"/api/assets/{result['id']}", {"title": title}),
            result=result,
            action="setting the title",
        )
        result["title"] = title
    if tags:
        await _after_create_step(
            ics.put_json(f"/api/assets/{result['id']}/tags", {"tags": tags}),
            result=result,
            action="setting the tags",
        )
    if project_id:
        await _after_create_step(
            _attach_to_project(result["slug"], project_id),
            result=result,
            action="attaching to the project",
        )


async def _attach_to_project(slug: str, project_id: UUID) -> dict[str, Any]:
    """`PATCH /api/assets/by-slug/{slug}/project`: the only way to set
    project_id; the ICS create endpoints do not accept that field."""
    return await runtime.require_ics().patch_json(
        f"/api/assets/by-slug/{slug}/project", {"project_id": str(project_id)}
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ics_asset_create_md",
        title="Create a markdown file",
        description=(
            "New md_single asset. Returns slug + share_url (link in "
            '`share_mode`; default org_sso). `share_mode="public"` follows the '
            "session mode and `confirm` (dry_run previews it).\n\n"
            "Content via **exactly one** of: `content` (inline text) or "
            "`content_path` (local path; recommended over a few KB). "
            "`project_id` attaches the asset to a project (requires the "
            "owner/editor role in the project)."
        ),
        annotations=MUTATING,
        output_schema=output_or_preview(M.CreateMdOut),
    )
    @map_ics_errors(hints=METADATA_HINTS)
    async def ics_asset_create_md(
        ctx: Context, payload: M.CreateMdIn, confirm: M.ConfirmFlag = None
    ) -> M.CreateMdOut | dict[str, Any]:
        preview = await confirm_public_create(
            ctx, payload.share_mode, target=f"new asset {payload.title!r}", confirm=confirm
        )
        if preview is not None:
            return preview
        ics = runtime.require_ics()
        raw = file_bytes(payload.content, None, payload.content_path)
        files = [("file", (_md_filename(payload.title), raw, "text/markdown"))]
        # share_mode goes in the query string: upload_markdown declares it as
        # `Query()` and silently ignores a form field of that name.
        params = {"share_mode": payload.share_mode} if payload.share_mode else None
        meta = create_metadata_fields(payload.doc_type, payload.summary)
        result = await ics.post_multipart(
            "/api/assets", files=files, data=meta or None, params=params
        )
        # The backend derives the title from the file name; the filename is
        # already faithful (see _md_filename), so the title PATCH is a safety net
        # for server-side normalization, not the regular path.
        await apply_create_steps(
            result, title=payload.title or None, tags=payload.tags, project_id=payload.project_id
        )
        try:
            await ctx.info(f"Created asset {result['slug']}")
        except Exception as e:
            log.debug("ctx.info dropped", error=str(e))
        return M.CreateMdOut(**result)

    @mcp.tool(
        name="ics_asset_create_collection",
        title="Create a markdown collection (vault)",
        description=(
            "Multi-file markdown vault with [[wikilink]] links.\n\n"
            "`entry_path` names the start file (must be one of "
            "`files[].path`); when omitted ICS picks: the shallowest "
            "README.md/index.md, and if there is none, the first "
            "alphabetically.\n\n"
            "Each file: exactly one of `content` (inline text) or `content_path` "
            "(local path; recommended over a few KB). `project_id` "
            "attaches the vault to a project (requires the owner/editor role). "
            '`share_mode="public"` follows the session mode and `confirm` '
            "(dry_run previews it)."
        ),
        annotations=MUTATING,
        output_schema=output_or_preview(M.CreateCollectionOut),
    )
    @map_ics_errors(hints=METADATA_HINTS)
    async def ics_asset_create_collection(
        ctx: Context, payload: M.CreateCollectionIn, confirm: M.ConfirmFlag = None
    ) -> M.CreateCollectionOut | dict[str, Any]:
        preview = await confirm_public_create(
            ctx, payload.share_mode, target=f"new vault {payload.title!r}", confirm=confirm
        )
        if preview is not None:
            return preview
        ics = runtime.require_ics()
        # share_mode goes in the query string; the title (derived from the entry
        # file) and the project are follow-up calls.
        params = {"share_mode": payload.share_mode} if payload.share_mode else None

        async def send(mp: list[Any], paths: list[str]) -> dict[str, Any]:
            data: dict[str, Any] = {
                "paths": paths,
                **create_metadata_fields(payload.doc_type, payload.summary),
            }
            if payload.entry_path is not None:
                data["entry_path"] = payload.entry_path
            return await ics.post_multipart(
                "/api/assets/collection", files=mp, data=data, params=params
            )

        result = await upload_files(
            ctx, payload.files, send, message=f"Uploading {len(payload.files)} files"
        )
        if payload.entry_path is not None and result.get("entry_path") != payload.entry_path:
            # Post-condition: a backend without entry_path support would silently
            # ignore the Form field, so we detect it from the response instead of
            # handing back a vault that opens on the wrong file.
            raise ICSError(
                "entry_path_not_applied",
                f"Asset created (slug={result['slug']}, id={result['id']}), "
                f"but ICS chose entry {result.get('entry_path')!r} instead of "
                f"the requested {payload.entry_path!r}.",
                hint=(
                    "The ICS backend probably does not support entry_path yet. "
                    "Upgrade ICS or omit the parameter."
                ),
                data={"id": str(result["id"]), "slug": result["slug"]},
            )
        await apply_create_steps(
            result, title=payload.title, tags=payload.tags, project_id=payload.project_id
        )
        return M.CreateCollectionOut(**result)

    @mcp.tool(
        name="ics_asset_rename",
        title="Rename",
        description="Changes the asset `title`. The slug stays.",
        annotations=MUTATING_IDEMP,
    )
    @map_ics_errors
    async def ics_asset_rename(slug_or_id: str, title: str) -> dict[str, Any]:
        asset_id, _ = await resolve_id(slug_or_id)
        return await runtime.require_ics().patch_json(f"/api/assets/{asset_id}", {"title": title})

    @mcp.tool(
        name="ics_asset_update_content",
        title="Update file content",
        description=(
            "Overwrites the content of a single file. Creates a new version: "
            "reversible via `ics_asset_restore_version`.\n\n"
            "Argument `path`:\n"
            "- `md_single`: omit `path` (the asset is one file, no path).\n"
            "- `md_collection`: `path` is **required**: names the file inside "
            "the vault (e.g. `notes/intro.md`). Without `path` it returns an error.\n\n"
            "Content via **exactly one** of: `content` (inline text) or "
            "`content_path` (local path; recommended over a few KB).\n\n"
            "When not to use: for `html_bundle` use "
            "`ics_asset_html_replace_bundle` (per-file edits are blocked). "
            "To replace many files at once in an `md_collection` use "
            "`ics_asset_new_version` (one new version instead of N separate ones)."
        ),
        annotations=DESTRUCTIVE,
    )
    @guarded(
        "update_content",
        target=lambda slug_or_id, content=None, path=None, **_: (
            f"{slug_or_id}{':' + path if path else ''}"
        ),
    )
    @map_ics_errors
    async def ics_asset_update_content(
        ctx: Context,
        slug_or_id: str,
        content: str | None = None,
        content_path: str | None = None,
        path: str | None = None,
        confirm: M.ConfirmFlag = None,
    ) -> dict[str, Any]:
        asset_id, _ = await resolve_id(slug_or_id)
        raw = file_bytes(content, None, content_path)
        body: dict[str, Any] = {"content": raw.decode("utf-8")}
        if path:
            body["path"] = path
        result = await runtime.require_ics().put_json(f"/api/assets/{asset_id}/content", body)
        invalidate_slug_cache(ctx, slug_or_id)
        return result

    @mcp.tool(
        name="ics_asset_add_file",
        title="Add a file to a collection",
        description=(
            "Adds a new `.md` file to an md_collection (this kind only; "
            "for html_bundle use `ics_asset_html_replace_bundle`).\n\n"
            "Provide **exactly one** of: `content` (inline text) or `content_path` "
            "(local path; recommended over a few KB)."
        ),
        annotations=MUTATING,
    )
    @map_ics_errors
    async def ics_asset_add_file(
        ctx: Context,
        slug_or_id: str,
        path: str,
        content: str | None = None,
        content_path: str | None = None,
    ) -> dict[str, Any]:
        asset_id, _ = await resolve_id(slug_or_id)
        raw = file_bytes(content, None, content_path)
        result = await runtime.require_ics().post_multipart(
            f"/api/assets/{asset_id}/files",
            files=[("file", (path.split("/")[-1], raw, "text/markdown"))],
            data={"path": path},
        )
        invalidate_slug_cache(ctx, slug_or_id)
        return result

    @mcp.tool(
        name="ics_asset_create_empty_file",
        title="Create an empty file in a collection",
        description="Empty placeholder file in an md_collection.",
        annotations=MUTATING,
    )
    @map_ics_errors
    async def ics_asset_create_empty_file(
        ctx: Context, slug_or_id: str, path: str, change_note: M.ChangeNoteArg = None
    ) -> dict[str, Any]:
        asset_id, _ = await resolve_id(slug_or_id)
        body: dict[str, Any] = {"path": path}
        if change_note:
            body["change_note"] = change_note
        result = await runtime.require_ics().post_json(f"/api/assets/{asset_id}/files/empty", body)
        invalidate_slug_cache(ctx, slug_or_id)
        return result

    @mcp.tool(
        name="ics_asset_move_file",
        title="Move a file in a collection",
        description="Changes the file path. Idempotent.",
        annotations=DESTRUCTIVE_IDEMP,
    )
    @guarded(
        "move_file",
        target=lambda slug_or_id, from_path, to_path, **_: f"{slug_or_id}: {from_path} → {to_path}",
    )
    @map_ics_errors
    async def ics_asset_move_file(
        ctx: Context,
        slug_or_id: str,
        from_path: str,
        to_path: str,
        confirm: M.ConfirmFlag = None,
    ) -> dict[str, Any]:
        asset_id, _ = await resolve_id(slug_or_id)
        result = await runtime.require_ics().patch_json(
            f"/api/assets/{asset_id}/files/move",
            {"from_path": from_path, "to_path": to_path},
        )
        invalidate_slug_cache(ctx, slug_or_id)
        return result

    @mcp.tool(
        name="ics_asset_delete_file",
        title="Delete a file from a collection",
        description="Deletes a specific file from an md_collection or html_bundle.",
        annotations=DESTRUCTIVE,
    )
    @guarded("delete_file", target=lambda slug_or_id, path, **_: f"{slug_or_id}:{path}")
    @map_ics_errors
    async def ics_asset_delete_file(
        ctx: Context, slug_or_id: str, path: str, confirm: M.ConfirmFlag = None
    ) -> dict[str, Any]:
        asset_id, _ = await resolve_id(slug_or_id)
        result = await runtime.require_ics().delete_json(
            f"/api/assets/{asset_id}/files", params={"path": path}
        )
        invalidate_slug_cache(ctx, slug_or_id)
        return result

    @mcp.tool(
        name="ics_asset_delete",
        title="Delete an asset (soft delete)",
        description="Soft delete. Can be undone via `ics_asset_undelete`.",
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
        name="ics_asset_undelete",
        title="Restore a deleted asset",
        description=(
            "Undoes a soft delete. Requires the asset UUID (slug lookup does not work for "
            "deleted assets). Share links are not restored."
        ),
        annotations=MUTATING_IDEMP,
    )
    @map_ics_errors
    async def ics_asset_undelete(asset_id: str) -> dict[str, Any]:
        require_uuid(
            asset_id,
            code="id_required",
            hint="Use the UUID from the audit log or an earlier output.",
        )
        return await runtime.require_ics().post_json(f"/api/assets/{asset_id}/undelete")

    @mcp.tool(
        name="ics_asset_pin",
        title="Pin or unpin an asset",
        description="Pins the asset to the top of the list; `pinned=false` removes the pin. Idempotent.",
        annotations=MUTATING_IDEMP,
    )
    @map_ics_errors
    async def ics_asset_pin(slug_or_id: str, pinned: bool = True) -> dict[str, Any]:
        asset_id, _ = await resolve_id(slug_or_id)
        ics = runtime.require_ics()
        if pinned:
            return await ics.post_json(f"/api/assets/{asset_id}/pin")
        return await ics.delete_json(f"/api/assets/{asset_id}/pin")

    @mcp.tool(
        name="ics_asset_set_tags",
        title="Set tags",
        description="Replaces the whole tag list (max 20, kebab-case).",
        annotations=MUTATING_IDEMP,
    )
    @map_ics_errors
    async def ics_asset_set_tags(ctx: Context, slug_or_id: str, tags: M.TagList) -> dict[str, Any]:
        asset_id, _ = await resolve_id(slug_or_id)
        result = await runtime.require_ics().put_json(
            f"/api/assets/{asset_id}/tags", {"tags": tags}
        )
        invalidate_slug_cache(ctx, slug_or_id)
        return result
