"""Confirm caller-keyed writes through the backend's durable receipt, without replay."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from ics_mcp import models as M
from ics_mcp._runtime import runtime
from ics_mcp.errors import ICSError

RECOVERY_HINT = (
    "The publication outcome is unknown. Use ics_publication_get with the same "
    "publication and original project_id. A missing receipt is inconclusive; "
    "do not create a new key or blindly repeat the mutation."
)


def require_expected_version(publication: M.PublicationIn | None, expected: int | None) -> None:
    if publication is not None and expected is None:
        raise ICSError(
            "invalid_argument",
            "A keyed replacement requires expected_version.",
            field="expected_version",
        )


async def publication_project(
    publication: M.PublicationIn | None, meta: dict[str, Any]
) -> str | None:
    """The UUID lookup omits scope; obtain full metadata before dispatching a keyed write."""
    if publication is None:
        return None
    scoped = meta
    if "project_id" not in scoped and isinstance(meta.get("slug"), str):
        scoped = await runtime.require_ics().get_json(f"/api/assets/by-slug/{meta['slug']}/meta")
    try:
        if scoped.get("id") != meta["id"]:
            raise ValueError("Asset identity changed during metadata lookup.")
        project = scoped["project_id"]
        return str(UUID(project)) if project is not None else None
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ICSError(
            "invalid_response",
            "ICS did not provide the asset's publication project scope.",
            field="project_id",
        ) from error


def _unknown(
    error: ICSError,
    publication: M.PublicationIn,
    project_id: str | None,
    result: dict[str, Any] | None = None,
) -> ICSError:
    return ICSError(
        error.code,
        error.message,
        status=error.status,
        field=error.field,
        hint=RECOVERY_HINT,
        data={
            **error.data,
            "outcome": "unknown",
            "publication": publication.model_dump(),
            "project_id": project_id,
            **({"result": result} if result is not None else {}),
        },
    )


async def read_publication(
    publication: M.PublicationIn,
    project_id: str | None,
) -> M.PublicationReceiptOut:
    params = {"order_id": publication.order_id, "role": publication.role}
    if project_id is not None:
        params["project_id"] = project_id
    try:
        data = await runtime.require_ics().get_json(
            f"/api/assets/publications/{publication.id}", params=params
        )
        receipt = M.PublicationReceiptOut.model_validate(data)
        scope = str(receipt.project_id) if receipt.project_id is not None else None
        if (receipt.publication_id, receipt.order_id, receipt.role, scope) != (
            publication.id,
            publication.order_id,
            publication.role,
            project_id,
        ):
            raise ValueError("Receipt identity does not match the requested scope.")
        if str(receipt.result.get("id")) != str(receipt.asset_id):
            raise ValueError("Receipt result does not name its asset.")
        if "version" in receipt.result and receipt.result["version"] != receipt.version:
            raise ValueError("Receipt result does not name its version.")
        return receipt
    except ICSError as error:
        raise _unknown(error, publication, project_id) from error
    except (ValidationError, ValueError, TypeError) as error:
        raise _unknown(
            ICSError("publication_unconfirmed", "ICS returned an invalid publication receipt."),
            publication,
            project_id,
        ) from error


async def publish(
    request: Callable[[], Awaitable[dict[str, Any]]],
    publication: M.PublicationIn | None,
    project_id: str | None,
) -> dict[str, Any]:
    if publication is None:
        return await request()
    try:
        result = await request()
    except ICSError as error:
        if error.code == "ics_unreachable" or (error.status is not None and error.status >= 500):
            raise _unknown(error, publication, project_id) from error
        raise
    except (ValueError, TypeError) as error:
        raise _unknown(
            ICSError("publication_unconfirmed", "ICS returned an invalid mutation response."),
            publication,
            project_id,
        ) from error
    try:
        receipt = await read_publication(publication, project_id)
        if receipt.result != result:
            raise ValueError("Receipt result differs from the mutation response.")
    except (ICSError, ValueError) as error:
        raise _unknown(
            ICSError(
                "publication_unconfirmed",
                "The mutation response has no matching confirmed receipt.",
            ),
            publication,
            project_id,
            result if isinstance(result, dict) else None,
        ) from error
    return {
        **result,
        "version": receipt.version,
        "publication_receipt": receipt.model_dump(mode="json"),
    }
