"""Read the original committed publication result after an ambiguous write."""

from uuid import UUID

from fastmcp import FastMCP

from ics_mcp import models as M
from ics_mcp._helpers import map_ics_errors
from ics_mcp._publication import read_publication
from ics_mcp.tools._annotations import RO_IDEMP


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ics_publication_get",
        title="Read a publication receipt",
        description=(
            "Read the confirmed asset/version for the original publication identity and "
            "project_id. Use after a timeout or unknown result, without another create. "
            "A missing receipt is inconclusive. Never generate a replacement key. "
            "The confirmed version may be older than the asset's current version."
        ),
        annotations=RO_IDEMP,
    )
    @map_ics_errors
    async def ics_publication_get(
        publication: M.PublicationIn,
        project_id: UUID | None = None,
    ) -> M.PublicationReceiptOut:
        return await read_publication(publication, str(project_id) if project_id else None)
