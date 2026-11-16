"""Explicit HTTP/PostgreSQL/Redis contract smoke; not part of hermetic unit tests.

Run through scripts/test-publication-backend.sh with the reviewed ICS checkout.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from fastmcp.exceptions import ToolError

from ics_mcp._runtime import runtime
from ics_mcp.auth.token_store import TokenPair, TokenStore
from ics_mcp.config import Settings
from ics_mcp.ics_client import ICSClient
from ics_mcp.server import build_mcp
from tests.conftest import call_tool


class LostAckTransport(httpx.AsyncHTTPTransport):
    """Discard one response only after the real server has finished its POST."""

    drop_next_post = False

    def __init__(self):
        super().__init__()
        self.posts = 0

    async def handle_async_request(self, request):
        response = await super().handle_async_request(request)
        if request.method == "POST":
            self.posts += 1
            if self.drop_next_post:
                self.drop_next_post = False
                await response.aread()
                await response.aclose()
                assert response.status_code == 201
                raise httpx.ReadTimeout(
                    "Synthetic lost acknowledgement after commit", request=request
                )
        return response


@pytest.fixture
async def backend(tmp_path):
    root = Path(os.environ["ICS_TEST_BACKEND_ROOT"])
    tmp_path.chmod(0o700)
    env = {key: value for key, value in os.environ.items() if not key.startswith("ICS_")}
    env.update(
        ICS_DATABASE_URL=os.environ["ICS_TEST_DATABASE_URL"],
        ICS_REDIS_URL=os.environ["ICS_TEST_REDIS_URL"],
        ICS_STORAGE_URL=f"fs://{tmp_path / 'storage'}",
        ICS_DEBUG="1",
        ICS_ALLOWED_DOMAINS="example.com",
        ICS_OCR_ENABLED="false",
    )
    log = (tmp_path / "server.log").open("w")
    process = subprocess.Popen(
        [
            str(root / "backend/.venv/bin/python"),
            str(Path(__file__).parent / "fixtures/publication_backend_server.py"),
            str(root),
            str(tmp_path),
        ],
        env=env,
        stdout=log,
        stderr=log,
    )
    try:
        deadline = time.monotonic() + 30
        ready = tmp_path / "ready.json"
        while not ready.exists():
            assert process.poll() is None, f"Backend exited; inspect {tmp_path / 'server.log'}"
            assert time.monotonic() < deadline, "Backend startup timed out"
            await asyncio.sleep(0.1)
        credentials = json.loads(ready.read_text())
        ready.unlink()
        url = credentials.pop("url")
        transport = LostAckTransport()
        async with httpx.AsyncClient(transport=transport) as http:
            while True:
                assert process.poll() is None, f"Backend exited; inspect {tmp_path / 'server.log'}"
                try:
                    response = await http.get(f"{url}/healthz")
                    if response.status_code < 500:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "Backend did not accept HTTP"
                await asyncio.sleep(0.1)
            store = TokenStore(
                service=f"publication-smoke-{tmp_path.name}", fallback_path=tmp_path / "tokens"
            )
            store.save(
                TokenPair(
                    access_token=credentials.pop("token"),
                    refresh_token="unused",
                    expires_at=time.time() + 600,
                    scope="ics",
                    resource=f"{url}/mcp",
                )
            )
            settings = Settings(
                base_url=url, mcp_resource_uri=f"{url}/mcp", mcp_oauth_client_id="publication-smoke"
            )
            runtime.ics = ICSClient(settings, store, http)
            try:
                yield (
                    build_mcp(settings),
                    credentials["project_id"],
                    transport,
                    tmp_path / "report.pdf",
                )
            finally:
                runtime.ics = None
                store.delete()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()


def key(name):
    return {"id": name, "order_id": "smoke-delivery", "role": "report"}


async def test_real_create_replace_replay_and_lost_ack(backend):
    mcp, project, transport, pdf = backend
    create = {
        "payload": {
            "title": "Receipt report",
            "entry_path": "index.html",
            "files": [{"path": "index.html", "content_text": "<h1>First</h1>"}],
            "project_id": project,
            "publication": key("create"),
        }
    }
    first = await call_tool(mcp, "ics_asset_create_html", create)
    assert first["version"] == 1
    assert first["publication_receipt"]["project_id"] == project
    assert first["publication_receipt"]["asset_id"] == first["id"]
    assert await call_tool(mcp, "ics_asset_create_html", create) == first
    lost_create = {"payload": {**create["payload"], "publication": key("lost-create")}}
    transport.drop_next_post = True
    posts = transport.posts
    with pytest.raises(ToolError) as caught:
        await call_tool(mcp, "ics_asset_create_html", lost_create)
    assert json.loads(str(caught.value))["data"]["outcome"] == "unknown"
    assert transport.posts == posts + 1
    recovered_create = await call_tool(
        mcp, "ics_publication_get", {"publication": key("lost-create"), "project_id": project}
    )
    assert recovered_create["version"] == 1
    assert recovered_create["asset_id"] != first["id"]
    replace = {
        "slug_or_id": first["id"],
        "entry_path": "index.html",
        "files": [{"path": "index.html", "content_text": "<h1>Second</h1>"}],
        "expected_version": 1,
        "publication": key("replace"),
        "confirm": True,
    }
    second = await call_tool(mcp, "ics_asset_html_replace_bundle", replace)
    assert second["version"] == 2
    # Lose the real 201 after version 3 commits; no second POST is made.
    lost = {
        **replace,
        "expected_version": 2,
        "publication": key("lost"),
        "files": [{"path": "index.html", "content_text": "<h1>Third</h1>"}],
    }
    transport.drop_next_post = True
    posts = transport.posts
    with pytest.raises(ToolError) as caught:
        await call_tool(mcp, "ics_asset_html_replace_bundle", lost)
    error = json.loads(str(caught.value))
    assert error["data"] == {
        "outcome": "unknown",
        "publication": key("lost"),
        "project_id": project,
    }
    assert transport.posts == posts + 1
    recovered = await call_tool(
        mcp, "ics_publication_get", {"publication": key("lost"), "project_id": project}
    )
    assert recovered["version"] == 3
    assert recovered["asset_id"] == first["id"]
    # A replay is an explicit caller action; version 2 stays version 2 after v3.
    assert await call_tool(mcp, "ics_asset_html_replace_bundle", replace) == second
    meta = await call_tool(mcp, "ics_asset_meta", {"slug_or_id": first["id"]})
    assert meta["version"] == 3
    md = await call_tool(
        mcp, "ics_asset_create_md", {"payload": {"title": "Markdown report", "content": "# First"}}
    )
    md_version = await call_tool(
        mcp,
        "ics_asset_new_version",
        {
            "slug_or_id": md["id"],
            "files": [{"path": "report.md", "content": "# Second"}],
            "expected_version": 1,
            "publication": key("markdown"),
            "confirm": True,
        },
    )
    assert md_version["version"] == md_version["publication_receipt"]["version"] == 2
    document = await call_tool(
        mcp, "ics_asset_create_document", {"payload": {"file_path": str(pdf)}}
    )
    document_version = await call_tool(
        mcp,
        "ics_asset_replace_document",
        {
            "slug_or_id": document["id"],
            "file_path": str(pdf),
            "expected_version": 1,
            "publication": key("pdf"),
            "confirm": True,
        },
    )
    assert document_version["version"] == document_version["publication_receipt"]["version"] == 2
