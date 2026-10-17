"""MCP resources: `ics://index`, plus RFC 6570 templates for an asset (optionally
`@v{version}`, `/outline`, `/file/{path}`) and a project."""

from __future__ import annotations

from typing import Any, cast

from fastmcp import FastMCP

from ics_mcp._payload import maybe_truncate
from ics_mcp._runtime import runtime
from ics_mcp.ics_ref import IcsRef, parse_version

# Kinds whose resource view inlines the entry content (file-mcp returns the
# converted Markdown for pdf_doc/office_doc).
_INLINE_KINDS = ("md_single", "pdf_doc", "office_doc")


async def _asset_view(ref: IcsRef) -> dict[str, Any]:
    ics = runtime.require_ics()
    meta = await ics.get_json(f"/api/assets/by-slug/{ref.slug}/meta")
    params = {"version": ref.version} if ref.version else None
    if meta["kind"] in _INLINE_KINDS:
        file = await ics.get_json(f"/api/assets/by-slug/{ref.slug}/file-mcp", params=params)
        view = {**meta, "content": file.get("content")}
    elif ref.version:
        # The outline always describes the current version, so an archived
        # version is shown by its own file tree instead.
        files = await ics.get_json(f"/api/assets/by-slug/{ref.slug}/files-mcp", params=params)
        view = {**meta, "files": maybe_truncate(files)}
    else:
        outline = await ics.get_json(f"/api/assets/by-slug/{ref.slug}/outline")
        view = {**meta, "outline": outline}
    if ref.version:
        view["read_version"] = ref.version
    return view


async def _file_content(ref: IcsRef) -> str:
    params: dict[str, Any] = {"path": ref.path}
    if ref.version:
        params["version"] = ref.version
    data = await runtime.require_ics().get_json(
        f"/api/assets/by-slug/{ref.slug}/file-mcp", params=params
    )
    return cast(str, data.get("content", ""))


def register(mcp: FastMCP) -> None:
    @mcp.resource("ics://index")
    async def index_resource() -> dict[str, Any]:
        """The user's first 50 assets. Quick list preview without filters;
        for filters or pagination use `ics_assets_list`."""
        return cast(
            dict[str, Any],
            await runtime.require_ics().get_json("/api/assets/index", params={"limit": 50}),
        )

    # Versioned templates are registered first: `{slug}` also matches
    # `abc@v2`, and FastMCP picks the first matching template on a tie, so the
    # unversioned handlers only see plain slugs.
    @mcp.resource("ics://asset/{slug}@v{version}")
    async def asset_version_resource(slug: str, version: str) -> dict[str, Any]:
        """Like `ics://asset/{slug}`, but for an archived version (read-only,
        nothing is restored). md_single/pdf_doc/office_doc inline that version's
        content; md_collection/html_bundle list that version's files (the outline
        only describes the current version). Version numbers come from
        `ics_asset_versions`."""
        return await _asset_view(IcsRef(slug=slug, version=parse_version(version)))

    @mcp.resource("ics://asset/{slug}@v{version}/file/{path}")
    async def asset_version_file_resource(slug: str, version: str, path: str) -> str:
        """Raw content of a file in an archived version of an `md_collection` or
        `html_bundle`. Same rules as `ics://asset/{slug}/file/{path}`; for a
        partial read use `ics_asset_read(slug, path, lines='N-M', version=N)`."""
        return await _file_content(IcsRef(slug=slug, version=parse_version(version), path=path))

    @mcp.resource("ics://asset/{slug}")
    async def asset_resource(slug: str) -> dict[str, Any]:
        """Meta + entry content (md_single inline, pdf_doc and office_doc as
        their converted text in Markdown, md_collection/html_bundle as an outline). Cheap preview when you want a quick look at an asset
        before deciding which tool to call. For the full content of an
        md_collection use `ics_asset_read(slug, path=...)`."""
        return await _asset_view(IcsRef(slug=slug))

    @mcp.resource("ics://asset/{slug}/outline")
    async def asset_outline_resource(slug: str) -> dict[str, Any]:
        """Outline only (structure of headings/files/wikilinks). Token-cheap
        first move before `ics_asset_read`. Cacheable by the MCP client."""
        return cast(
            dict[str, Any],
            await runtime.require_ics().get_json(f"/api/assets/by-slug/{slug}/outline"),
        )

    @mcp.resource("ics://asset/{slug}/file/{path}")
    async def asset_file_resource(slug: str, path: str) -> str:
        """Raw content of a file from an `md_collection` or `html_bundle` (text
        files; bundle binaries → error 415, use `ics_asset_read` with
        `encoding="base64"`). No line slicing; for a partial read use
        `ics_asset_read(slug, path, lines='N-M')`."""
        return await _file_content(IcsRef(slug=slug, path=path))

    @mcp.resource("ics://project/{slug}")
    async def project_resource(slug: str) -> dict[str, Any]:
        """Project metadata + the first 200 assets. For full pagination use
        `ics_assets_list(project_id=...)`."""
        # ICS caps the asset list at 200 and returns `assets_truncated=true`
        # (see `routes/projects/crud.py`). Tell the agent where to get the full
        # list instead of letting it infer from `len(assets) < asset_count`.
        data = await runtime.require_ics().get_json(f"/api/projects/{slug}")
        if data.get("assets_truncated"):
            data["hint"] = (
                f"The 'assets' list is truncated to 200/{data.get('asset_count')}. "
                f"Full pagination: ics_assets_list(project_id='{data.get('id')}', cursor=...)."
            )
        return cast(dict[str, Any], data)
