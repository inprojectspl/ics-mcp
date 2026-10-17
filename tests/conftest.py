"""Shared test fixtures and helpers.

Centralizes the boilerplate that every e2e and crypto test would
otherwise re-implement:

- `settings`: Pydantic Settings pointing at the fake ICS host.
- `real_client`: wired ICSClient bound into `runtime.ics`.
- `make_mcp`: factory that builds a FastMCP instance and registers
  one or more tool modules on it.
- `call_tool` / `read_resource` / `get_prompt`: thin adapters over
  FastMCP's underscore-prefixed internals. Single change point when
  the library renames them.
- `mock_resolve`: registers the canonical `by-slug/{slug}/meta`
  response used by every tool that calls `resolve_id`.
- Constants: `ICS`, `ASSET_ID`.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

# Environment defaults: must precede any `ics_mcp` import that touches
# Settings (config.py raises on missing audience in non-debug mode).
os.environ.setdefault("ICS_DEBUG", "1")
os.environ.setdefault("ICS_MCP_RESOURCE_URI", "https://ics.test/mcp")
os.environ.setdefault("ICS_BASE_URL", "https://ics.test")

import httpx
import keyring
import pytest
from fastmcp import FastMCP
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from ics_mcp import session as session_mod
from ics_mcp._runtime import runtime
from ics_mcp.auth.token_store import TokenPair, TokenStore
from ics_mcp.config import Settings
from ics_mcp.ics_client import ICSClient

ICS = "https://ics.test"
ASSET_ID = "12345678-1234-5678-1234-567812345678"


class MemoryKeyring(KeyringBackend):
    """Process-local keyring so tests never write to the OS keychain."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.entries: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        try:
            del self.entries[(service, username)]
        except KeyError:
            raise PasswordDeleteError(service) from None


@pytest.fixture(autouse=True)
def memory_keyring():
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def _allow_yolo_in_tests(monkeypatch):
    """Most tool tests switch the session to yolo to skip confirmations;
    the operator opt-in that production requires is granted here, and
    tests of the opt-in itself turn it back off."""
    from ics_mcp.config import get_settings

    monkeypatch.setattr(get_settings(), "mcp_allow_yolo", True)


@pytest.fixture(autouse=True)
def _isolate_session_state():
    """Session store is process-global keyed by session id; without a
    reset, `ics_session_set_mode('yolo')` in one test leaks into every
    later test that shares the key (in-process FastMCP calls do)."""
    session_mod.clear_all()
    yield
    session_mod.clear_all()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        base_url=ICS,
        mcp_resource_uri=f"{ICS}/mcp",
        mcp_oauth_client_id="ics-mcp-stdio",
    )


@pytest.fixture
async def real_client(settings, tmp_path):
    """Wired ICSClient bound into `runtime.ics` for the test.

    Saves a non-expiring token so tool calls don't trigger the
    interactive auth flow, then clears the global on teardown so
    parallel tests don't see stale state.
    """
    store = TokenStore(service=f"ics-mcp-test-{tmp_path.name}", fallback_path=tmp_path / "creds")
    store.save(
        TokenPair(
            access_token="tok",
            refresh_token="opaque",
            expires_at=10_000_000_000.0,
            scope="ics",
            resource=f"{ICS}/mcp",
        )
    )
    http = httpx.AsyncClient()
    client = ICSClient(settings, store, http)
    runtime.ics = client
    yield client
    runtime.ics = None
    store.delete()
    await http.aclose()


@pytest.fixture
def make_mcp():
    """Factory: `make_mcp(discovery, write_md)` returns a FastMCP with
    those tool modules registered."""

    def _make(*modules) -> FastMCP:
        mcp = FastMCP("t")
        for m in modules:
            m.register(mcp)
        return mcp

    return _make


@pytest.fixture
def ctx():
    """MagicMock Context that satisfies the (very loose) interface our
    tools touch: `info` and `report_progress` as awaitable no-ops."""
    c = MagicMock()
    c.session_id = "test"

    async def _info(_msg: str) -> None:
        return None

    async def _report(**_kw) -> None:
        return None

    c.info = _info
    c.report_progress = _report
    return c


# ---------------------------------------------------------------------------
# Thin adapters over FastMCP internals. Tests depend on these signatures, not
# `mcp._call_tool_mcp` directly, so a FastMCP rename is a one-line change.
# ---------------------------------------------------------------------------


async def call_tool(mcp: FastMCP, name: str, args: dict[str, Any]) -> Any:
    """Invokes a tool and returns the structured payload."""
    _, payload = await mcp._call_tool_mcp(name, args)
    return payload


async def list_tools(mcp: FastMCP):
    """The catalogue as clients see it (transforms applied)."""
    return await mcp.list_tools()


async def list_resources(mcp: FastMCP):
    return await mcp._list_resources()


async def list_resource_templates(mcp: FastMCP):
    return await mcp._list_resource_templates()


async def list_prompts(mcp: FastMCP):
    return await mcp._list_prompts()


async def read_resource(mcp: FastMCP, uri: str):
    return await mcp._read_resource_mcp(uri)


async def get_prompt(mcp: FastMCP, name: str, args: dict[str, Any]):
    return await mcp._get_prompt_mcp(name, args)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def mock_resolve(respx_mock, slug: str = "abc", asset_id: str = ASSET_ID):
    """Mocks the GET `/by-slug/{slug}/meta` response that `resolve_id`
    hits for every slug-input write tool."""
    return respx_mock.get(f"{ICS}/api/assets/by-slug/{slug}/meta").mock(
        return_value=httpx.Response(200, json={"id": asset_id, "slug": slug})
    )


def create_md_response(
    *,
    asset_id: str = ASSET_ID,
    slug: str = "abc",
    title: str | None = "T",
    share_url: str | None = None,
) -> dict[str, Any]:
    """Canonical shape of the `POST /api/assets` response, copied from ICS
    `routes/assets/crud.py::upload_markdown`. Mocks built from here (and not
    "from the model") are a schema-drift regression test: a field the API
    does not return has no business appearing in this builder."""
    return {
        "id": asset_id,
        "slug": slug,
        "title": title,
        "share_url": share_url if share_url is not None else f"{ICS}/s/tok",
    }


def create_collection_response(
    *,
    asset_id: str = ASSET_ID,
    slug: str = "vlt",
    title: str | None = "a",
    entry_path: str | None = "a.md",
    file_count: int = 2,
) -> dict[str, Any]:
    """Canonical shape of the `POST /api/assets/collection` response, copied
    from ICS `routes/assets/crud.py::upload_collection`. The default `title="a"`
    mirrors the server-side derivation (stem of the entry file, not the
    requested title); `version` and `share_url` are absent on purpose because
    the API does not return them."""
    return {
        "id": asset_id,
        "slug": slug,
        "title": title,
        "kind": "md_collection",
        "entry_path": entry_path,
        "file_count": file_count,
    }


def asset_meta(
    *,
    slug: str = "abc",
    asset_id: str = ASSET_ID,
    kind: str = "md_single",
    **overrides: Any,
) -> dict[str, Any]:
    """Builder for the canonical AssetMeta response shape. Pydantic
    validates these fields, so a model drift breaks every test that uses
    this, which is exactly the catch we want."""
    base = {
        "id": asset_id,
        "slug": slug,
        "title": "T",
        "kind": kind,
        "size_bytes": 100,
        "version": 1,
        "updated_at": "2026-05-15T08:00:00Z",
        "pinned": False,
        "owner_id": asset_id,
        "project_id": None,
        "tags": [],
        "has_versions": False,
        "access_role": "owner_file",
    }
    base.update(overrides)
    return base
