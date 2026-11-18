"""Tool registration entrypoint."""

from __future__ import annotations

from fastmcp import FastMCP

from ics_mcp.tools import (
    discovery,
    lifecycle,
    metadata,
    micro_app_access,
    micro_applications,
    ocr,
    projects,
    publications,
    read,
    relations,
    session,
    share,
    tasks,
    write_documents,
    write_html,
    write_md,
    write_versions,
)
from ics_mcp.tools._arg_errors import ArgumentErrors
from ics_mcp.tools._catalog import CompactCatalog


def register_all(mcp: FastMCP) -> None:
    session.register(mcp)
    discovery.register(mcp)
    metadata.register(mcp)
    read.register(mcp)
    ocr.register(mcp)
    write_md.register(mcp)
    lifecycle.register(mcp)
    write_html.register(mcp)
    write_documents.register(mcp)
    write_versions.register(mcp)
    publications.register(mcp)
    relations.register(mcp)
    tasks.register(mcp)
    projects.register(mcp)
    share.register(mcp)
    micro_applications.register(mcp)
    micro_app_access.register(mcp)
    mcp.add_transform(CompactCatalog())
    mcp.add_middleware(ArgumentErrors())
