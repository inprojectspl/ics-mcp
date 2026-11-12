"""Who may use a micro-application: read the access picture, set one
person's or project's access to an exact target state.

Opening the app (a role on the asset) and what a person may do in it (the
app's roles and permissions) are separate in ICS; `ics_microapp_access_set`
sets both in one idempotent call, so an agent states the result instead of
replaying panel clicks.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from ics_mcp import models as M
from ics_mcp._helpers import guarded, map_ics_errors
from ics_mcp._runtime import runtime
from ics_mcp.errors import ICSError, raise_tool_error
from ics_mcp.tools._annotations import MUTATING_IDEMP, RO_IDEMP
from ics_mcp.tools.micro_applications import _asset_id

_BASE = "/api/micro-applications"
PermissionName = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[a-z][a-z0-9_.-]*$")]
RoleName = Annotated[str, Field(min_length=1, max_length=48, pattern=r"^[a-z][a-z0-9_]*$")]


def _can_open(user_email: str | None, gives: list[str], can_open: bool | None) -> bool | None:
    """A person given any role or permission must also be able to open the app."""
    if user_email is not None and can_open is None and gives:
        return True
    return can_open


def _describe(
    *,
    asset_id: str,
    user_email: str | None = None,
    project_id: str | None = None,
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
    can_open: bool | None = None,
    **_: Any,
) -> str:
    who = user_email or f"project {project_id}"
    gives = [f"role {r}" for r in sorted(roles or [])] + sorted(permissions or [])
    can_open = _can_open(user_email, gives, can_open)
    what = ", ".join(gives) or "nothing"
    opening = {True: "; may open the app", False: "; may not open the app", None: ""}[can_open]
    return f"{who} in {asset_id}: exactly {what}{opening}"


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ics_microapp_access",
        title="Who can use a micro-application",
        description=(
            "Read the access picture of one micro-application: `roles` (the app's "
            "named sets of permissions: `role`, `label`, `description`, "
            "`permissions`), `permissions` (each with its `label` and what it "
            "unlocks, e.g. `requests: create (own rows)` or `POST /v1/custom/... "
            "(approve)`, plus app.publish / app.control), `people` (email, `can_open`, "
            "how they reach the app, direct `roles` and `permissions`, "
            "`effective_permissions` with roles and projects included) and `projects` "
            "with their roles and permissions. Read it before "
            "ics_microapp_access_set to pick a role. Needs app.access.manage (owner "
            "of the app or of its project)."
        ),
        annotations=RO_IDEMP,
    )
    @map_ics_errors
    async def ics_microapp_access(asset_id: str) -> dict[str, Any]:
        aid = await _asset_id(asset_id)
        return dict(await runtime.require_ics().get_json(f"{_BASE}/{aid}/access"))

    @mcp.tool(
        name="ics_microapp_access_set",
        title="Set who can use a micro-application",
        description=(
            "Give or take access to a micro-application in one idempotent call: the "
            "person (`user_email`) or the members of a project (`project_id`) get "
            "EXACTLY `roles` plus `permissions` (missing ones are granted, extra ones "
            "revoked; an omitted list means none). Prefer `roles` (e.g. "
            '`roles=["reviewer"]`): a role gives what the active release defines for '
            "it, also after a new release changes it; `permissions` are for a "
            "single extra right beside them. For a person, `can_open` "
            "defaults to true when anything is given: ICS adds a viewer share if they "
            "cannot open the app yet. To remove a person: `roles=[]`, "
            "`permissions=[]`, `can_open=false`; when they still open the app through "
            "another role (project, editor), the answer names it in "
            "`still_opens_via`. ICS roles (viewer, editor, owner) decide what a "
            "person does with the asset, never in the app: no ICS role implies app "
            "roles, not even ownership, so set your own too. A project's app roles "
            "reach every accepted member alike, whatever their project role; give "
            "different roles to people directly. Returns `roles_added`, `roles_removed`, `added`, "
            "`removed`, `open_change` and the resulting person. Role and permission "
            "names come from ics_microapp_access. For people without an ICS account "
            "use ics_share_create_link(app_roles=[...]) instead."
        ),
        annotations=MUTATING_IDEMP,
    )
    @guarded("set_micro_application_access", target=_describe)
    @map_ics_errors
    async def ics_microapp_access_set(
        ctx: Context,
        asset_id: str,
        roles: Annotated[list[RoleName], Field(max_length=20)] | None = None,
        permissions: Annotated[list[PermissionName], Field(max_length=50)] | None = None,
        user_email: Annotated[str | None, Field(max_length=320)] = None,
        project_id: str | None = None,
        can_open: bool | None = None,
        confirm: M.ConfirmFlag = None,
    ) -> dict[str, Any]:
        if (user_email is None) == (project_id is None):
            raise_tool_error(
                ICSError(
                    "invalid_argument",
                    "give exactly one of user_email or project_id",
                    field="user_email",
                )
            )
        aid = await _asset_id(asset_id)
        roles, permissions = sorted(set(roles or [])), sorted(set(permissions or []))
        body: dict[str, Any] = {
            "roles": roles,
            "permissions": permissions,
            "can_open": _can_open(user_email, roles + permissions, can_open),
        }
        if user_email is not None:
            body["user_email"] = user_email
        else:
            body["project_id"] = project_id
        return dict(await runtime.require_ics().put_json(f"{_BASE}/{aid}/access", body))
