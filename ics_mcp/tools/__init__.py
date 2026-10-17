"""Tool registration entrypoint."""

from __future__ import annotations

from fastmcp import FastMCP

from ics_mcp.tools import (
    discovery,
    metadata,
    ocr,
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
    write_html.register(mcp)
    write_documents.register(mcp)
    write_versions.register(mcp)
    relations.register(mcp)
    tasks.register(mcp)
    share.register(mcp)
    mcp.add_transform(CompactCatalog())
    mcp.add_middleware(ArgumentErrors())
