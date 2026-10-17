"""Document metadata: summary, type, maintainer, review date, and the type list.
Editing metadata creates no version (ICS ADR-0015). The PATCH clears a field
on `null`; the tool maps an empty string to `null`, so an agent can clear a
field without a separate parameter."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ics_mcp import models as M
from ics_mcp._helpers import map_ics_errors, resolve_id
from ics_mcp._runtime import runtime
from ics_mcp.errors import ICSError
from ics_mcp.tools._annotations import MUTATING_IDEMP, RO_IDEMP
from ics_mcp.tools._metadata import METADATA_HINTS

_CLEARS = 'Empty string "" clears it; omit to keep it.'


async def resolve_maintainer(email: str, slug: str) -> str:
    """User id for `email`. ICS has no user lookup by e-mail for non-admins,
    so the candidates are the caller and the users the asset is shared with."""
    ics = runtime.require_ics()
    wanted = email.strip().casefold()
    me = await ics.whoami()
    if str(me.get("email", "")).casefold() == wanted:
        return str(me["user_id"])
    shares = await ics.get_json(f"/api/assets/by-slug/{slug}/shares")
    for share in shares if isinstance(shares, list) else []:
        if str(share.get("email", "")).casefold() == wanted:
            return str(share["user_id"])
    raise ICSError(
        "maintainer_unknown",
        f"No user {email} among you and the users this asset is shared with.",
        hint="Share the asset with that user first (`ics_share_grant_user`), then retry.",
        field="maintainer_email",
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ics_asset_set_meta",
        title="Set document metadata",
        description=(
            "Sets the summary, document type, maintainer, review date, language or "
            "properties of an asset without a new version. Only the given fields "
            "change. See `ics_help('tools')`."
        ),
        annotations=MUTATING_IDEMP,
    )
    @map_ics_errors(hints=METADATA_HINTS)
    async def ics_asset_set_meta(
        slug_or_id: str,
        summary: Annotated[
            str | None, Field(description=f"What the document is for, 1-3 sentences. {_CLEARS}")
        ] = None,
        doc_type: Annotated[
            str | None, Field(description=f"Key from `ics_doc_types`. {_CLEARS}")
        ] = None,
        maintainer_email: Annotated[
            str | None,
            Field(description=f"You or a user the asset is shared with. {_CLEARS}"),
        ] = None,
        review_due_at: Annotated[
            str | None, Field(description=f"RFC 3339 date-time. {_CLEARS}")
        ] = None,
        language: Annotated[
            str | None, Field(description=f"Language tag, e.g. 'en', 'pl'. {_CLEARS}")
        ] = None,
        properties: Annotated[
            dict[str, Any] | None,
            Field(description="Type-specific fields; replaces the whole object."),
        ] = None,
    ) -> dict[str, Any]:
        asset_id, meta = await resolve_id(slug_or_id)
        body: dict[str, Any] = {}
        for name, value in (
            ("summary", summary),
            ("doc_type", doc_type),
            ("review_due_at", review_due_at),
            ("language", language),
        ):
            if value is not None:
                body[name] = value or None
        if maintainer_email is not None:
            body["maintainer_id"] = (
                await resolve_maintainer(maintainer_email, str(meta["slug"]))
                if maintainer_email
                else None
            )
        if properties is not None:
            body["properties"] = properties
        if not body:
            raise ICSError(
                "invalid_argument",
                "Nothing to change: pass at least one metadata field.",
                hint="For example `summary=...` or `doc_type=...`.",
            )
        return await runtime.require_ics().patch_json(f"/api/assets/{asset_id}/meta", body)

    @mcp.tool(
        name="ics_doc_types",
        title="List document types",
        description=(
            "Document types available for `doc_type`: key, label, agent_hint "
            "(when to use the type) and default_review_days."
        ),
        annotations=RO_IDEMP,
    )
    @map_ics_errors
    async def ics_doc_types() -> M.DocTypesOut:
        rows = await runtime.require_ics().get_json("/api/doc-types")
        return M.DocTypesOut(doc_types=[M.DocTypeOut(**row) for row in rows])
