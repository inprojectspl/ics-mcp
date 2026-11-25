"""Projects: creating one and reading who belongs to it. Listing is in
`discovery`, the tracker links and key documents in `tasks`."""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote

from fastmcp import FastMCP
from pydantic import Field

from ics_mcp._helpers import map_ics_errors
from ics_mcp._runtime import runtime
from ics_mcp.tools._annotations import MUTATING, RO_IDEMP


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ics_project_create",
        title="Create a project",
        description=(
            "New ICS project owned by the caller: returns its `slug`, `id` and "
            "`my_role` (owner). Not idempotent: a repeated call makes a second "
            "project, so after a lost response look for it with `ics_projects_list` "
            "first. Put documents in it with `project_id` on create or "
            "`ics_asset_set_meta`; tracker links and key documents: "
            "`ics_project_links_set`."
        ),
        annotations=MUTATING,
    )
    @map_ics_errors
    async def ics_project_create(
        name: Annotated[str, Field(min_length=1, max_length=255)],
        description: Annotated[str | None, Field(max_length=4000)] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if description is not None:
            body["description"] = description
        return await runtime.require_ics().post_json("/api/projects", body)

    @mcp.tool(
        name="ics_project_members",
        title="List project members",
        description=(
            "People of one project (`project`: its slug from `ics_projects_list`): "
            "each with `email`, `display_name`, `role` (owner, editor, viewer), "
            "`status` ('member', or 'invited' while the invitation is not accepted, "
            "which gives no access yet) and the invitation dates. Answers who has "
            "access through the project; a person may also reach one document by "
            "a direct share (`ics_shares_list`). Any member may read it."
        ),
        annotations=RO_IDEMP,
    )
    @map_ics_errors
    async def ics_project_members(
        project: Annotated[str, Field(min_length=1, max_length=255)],
    ) -> dict[str, Any]:
        data = await runtime.require_ics().get_json(
            f"/api/projects/{quote(project, safe='')}/members"
        )
        members = [
            {
                "email": m.get("email"),
                "display_name": m.get("display_name"),
                "role": m.get("role"),
                "status": "member" if m.get("accepted_at") else "invited",
                "invited_at": m.get("invited_at"),
                "accepted_at": m.get("accepted_at"),
            }
            for m in data.get("members") or []
        ]
        return {
            "project": {
                "slug": data.get("slug"),
                "name": data.get("name"),
                "my_role": data.get("my_role"),
            },
            "member_count": data.get("member_count"),
            "members": members,
        }
