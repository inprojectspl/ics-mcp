"""Share tokens and bearer tokens never reach the logs."""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from ics_mcp import logging as ics_logging
from ics_mcp.tools import share
from tests.conftest import ICS, call_tool
from tests.test_share_resolve import _resolve_response

TOKEN = "test-share-token-not-a-secret-0000000000"


@pytest.mark.asyncio
@respx.mock(assert_all_called=False)
async def test_share_resolve_does_not_log_the_token(real_client, respx_mock, make_mcp, caplog):
    ics_logging.configure("INFO")
    respx_mock.post(f"{ICS}/api/share/{TOKEN}/resolve").mock(
        return_value=httpx.Response(200, json=_resolve_response())
    )
    caplog.set_level(logging.DEBUG)
    mcp = make_mcp(share)
    await call_tool(mcp, "ics_share_resolve", {"share_link": f"{ICS}/s/{TOKEN}"})
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert TOKEN not in logged
    assert not any("Bearer" in r.getMessage() for r in caplog.records)


def test_configure_keeps_http_client_loggers_quiet():
    ics_logging.configure("DEBUG")
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING
