"""Entrypoint.

Stdio (default): `python -m ics_mcp` or `ics-mcp`.
HTTP: `ICS_MCP_TRANSPORT=http python -m ics_mcp`.
"""

from __future__ import annotations

from ics_mcp.config import get_settings
from ics_mcp.server import mcp


def main() -> int:
    settings = get_settings()
    if settings.mcp_transport == "http":
        import uvicorn

        from ics_mcp.http_app import build_http_app

        uvicorn.run(
            build_http_app(mcp, settings), host=settings.mcp_http_host, port=settings.mcp_http_port
        )
    else:
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
