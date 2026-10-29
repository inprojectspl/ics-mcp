"""Tests for the DRY helpers: decorators (map_ics_errors, guarded),
slug/id resolution, file_bytes, require_uuid, upload_files.

These are the foundations every tool relies on; a bug here propagates
to every tool.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.exceptions import ToolError

from ics_mcp._helpers import (
    _is_uuid,
    guarded,
    map_ics_errors,
    require_uuid,
    resolve_id,
    resolve_slug,
)
from ics_mcp._runtime import runtime
from ics_mcp._uploads import file_bytes, upload_files
from ics_mcp.errors import ICSError


@pytest.fixture
def fake_ics(monkeypatch):
    """Bind a mocked ICSClient to the runtime singleton for the test."""
    ics = MagicMock()
    ics.get_json = AsyncMock()
    runtime.ics = ics
    yield ics
    runtime.ics = None


@dataclass
class _StubCollectionFile:
    path: str
    content: str | None = None
    content_path: str | None = None


@dataclass
class _StubHtmlFile:
    path: str
    content_text: str | None = None
    content_base64: str | None = None
    content_path: str | None = None
    mime: str | None = None


class FakeContext:
    """Bare context for upload_files progress emission."""

    async def report_progress(self, **kwargs: Any) -> None:
        return None

    async def info(self, msg: str) -> None:
        return None


# ============================================================
#  _is_uuid / require_uuid
# ============================================================


def test_is_uuid_accepts_canonical_form():
    assert _is_uuid("12345678-1234-5678-1234-567812345678") is True


def test_is_uuid_rejects_slug():
    assert _is_uuid("abc12345") is False


def test_is_uuid_rejects_empty():
    assert _is_uuid("") is False


def test_require_uuid_returns_input_when_valid():
    assert (
        require_uuid("12345678-1234-5678-1234-567812345678")
        == "12345678-1234-5678-1234-567812345678"
    )


def test_require_uuid_raises_tool_error_on_slug():
    with pytest.raises(ToolError):
        require_uuid("not-a-uuid", hint="use the id from the audit log")


# ============================================================
#  resolve_slug / resolve_id
# ============================================================


@pytest.mark.asyncio
async def test_resolve_slug_passes_through_slug_without_fetch(fake_ics):
    out = await resolve_slug("my-slug")
    assert out == "my-slug"
    fake_ics.get_json.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_slug_fetches_when_uuid_given(fake_ics):
    fake_ics.get_json.return_value = {
        "slug": "resolved-slug",
        "id": "12345678-1234-5678-1234-567812345678",
    }
    out = await resolve_slug("12345678-1234-5678-1234-567812345678")
    assert out == "resolved-slug"
    fake_ics.get_json.assert_awaited_once_with("/api/assets/12345678-1234-5678-1234-567812345678")


@pytest.mark.asyncio
async def test_resolve_id_with_uuid_hits_legacy_endpoint(fake_ics):
    fake_ics.get_json.return_value = {"id": "12345678-1234-5678-1234-567812345678", "slug": "s"}
    asset_id, meta = await resolve_id("12345678-1234-5678-1234-567812345678")
    assert asset_id == "12345678-1234-5678-1234-567812345678"
    assert meta["slug"] == "s"


@pytest.mark.asyncio
async def test_resolve_id_with_slug_hits_meta_endpoint(fake_ics):
    fake_ics.get_json.return_value = {"id": "uuid-here", "slug": "the-slug"}
    asset_id, meta = await resolve_id("the-slug")
    assert asset_id == "uuid-here"
    fake_ics.get_json.assert_awaited_once_with("/api/assets/by-slug/the-slug/meta")
    assert meta["slug"] == "the-slug"


# ============================================================
#  file_bytes XOR validation
# ============================================================


def test_file_bytes_text_only_returns_utf8():
    assert file_bytes("hello", None) == b"hello"


def test_file_bytes_base64_only_decodes():
    encoded = base64.b64encode(b"hello").decode()
    assert file_bytes(None, encoded) == b"hello"


def test_file_bytes_both_present_raises():
    with pytest.raises(ToolError):
        file_bytes("x", base64.b64encode(b"y").decode())


def test_file_bytes_neither_present_raises():
    with pytest.raises(ToolError):
        file_bytes(None, None)


def test_file_bytes_content_path_reads_file(tmp_path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello from disk")
    assert file_bytes(None, None, str(p)) == b"hello from disk"


def test_file_bytes_content_path_expands_user(tmp_path, monkeypatch):
    p = tmp_path / "u.txt"
    p.write_bytes(b"home")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert file_bytes(None, None, "~/u.txt") == b"home"


def test_file_bytes_content_path_missing_raises(tmp_path):
    with pytest.raises(ToolError):
        file_bytes(None, None, str(tmp_path / "nope.txt"))


def test_file_bytes_text_and_path_mutually_exclusive(tmp_path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"x")
    with pytest.raises(ToolError):
        file_bytes("inline", None, str(p))


# ============================================================
#  map_ics_errors decorator
# ============================================================


@pytest.mark.asyncio
async def test_map_ics_errors_passes_through_success():
    @map_ics_errors
    async def f(x: int) -> int:
        return x * 2

    assert await f(3) == 6


@pytest.mark.asyncio
async def test_map_ics_errors_converts_ics_error_to_tool_error():
    @map_ics_errors
    async def f() -> None:
        raise ICSError("not_found", "missing", hint="check slug")

    with pytest.raises(ToolError):
        await f()


@pytest.mark.asyncio
async def test_map_ics_errors_lets_unrelated_exceptions_propagate_via_internal_error():
    """Non-ICSError exceptions get wrapped as internal_error ToolError."""

    @map_ics_errors
    async def f() -> None:
        raise ValueError("internal")

    with pytest.raises((ToolError, ValueError)):
        await f()


# ============================================================
#  guarded decorator
# ============================================================


@pytest.mark.asyncio
async def test_guarded_yolo_mode_skips_confirm_and_runs(monkeypatch):
    monkeypatch.setattr("ics_mcp._helpers.get_mode", lambda ctx: "yolo")

    @guarded("delete", target="abc")
    async def fn(ctx, slug_or_id: str, confirm: bool | None = None) -> dict:
        return {"deleted": True, "slug": slug_or_id}

    ctx = MagicMock()
    out = await fn(ctx, slug_or_id="abc")
    assert out == {"deleted": True, "slug": "abc"}


@pytest.mark.asyncio
async def test_guarded_dry_run_returns_preview_without_running(monkeypatch):
    monkeypatch.setattr("ics_mcp._helpers.get_mode", lambda ctx: "dry_run")
    fn_was_called = False

    @guarded("delete", target=lambda slug_or_id, **_: slug_or_id)
    async def fn(ctx, slug_or_id: str, confirm: bool | None = None) -> dict:
        nonlocal fn_was_called
        fn_was_called = True
        return {"deleted": True}

    ctx = MagicMock()
    result = await fn(ctx, slug_or_id="abc")
    assert isinstance(result, dict)
    assert result["action"] == "delete"
    assert result["target"] == "abc"
    assert fn_was_called is False


@pytest.mark.asyncio
async def test_guarded_explicit_confirm_true_runs_in_interactive_mode(monkeypatch):
    monkeypatch.setattr("ics_mcp._helpers.get_mode", lambda ctx: "interactive")

    @guarded("delete", target="abc")
    async def fn(ctx, slug_or_id: str, confirm: bool | None = None) -> dict:
        return {"ran": True}

    ctx = MagicMock()
    out = await fn(ctx, slug_or_id="abc", confirm=True)
    assert out == {"ran": True}


@pytest.mark.asyncio
async def test_guarded_target_callable_receives_kwargs(monkeypatch):
    monkeypatch.setattr("ics_mcp._helpers.get_mode", lambda ctx: "dry_run")
    seen_kwargs: dict = {}

    def target_fn(**kwargs):
        seen_kwargs.update(kwargs)
        return f"{kwargs['slug_or_id']}:{kwargs['path']}"

    @guarded("delete_file", target=target_fn)
    async def fn(ctx, slug_or_id: str, path: str, confirm: bool | None = None) -> dict:
        return {}

    ctx = MagicMock()
    result = await fn(ctx, slug_or_id="abc", path="x.md")
    assert result["target"] == "abc:x.md"
    assert seen_kwargs == {"slug_or_id": "abc", "path": "x.md", "ctx": ctx}


@pytest.mark.asyncio
async def test_guarded_awaits_an_async_target_only_when_it_is_read(monkeypatch):
    mode = {"value": "dry_run"}
    monkeypatch.setattr("ics_mcp._helpers.get_mode", lambda ctx: mode["value"])
    calls: list[str] = []

    async def target_fn(slug_or_id: str, **_):
        calls.append(slug_or_id)
        return f"Title ({slug_or_id})"

    @guarded("delete", target=target_fn)
    async def fn(ctx, slug_or_id: str, confirm: bool | None = None) -> dict:
        return {"done": True}

    assert (await fn(MagicMock(), slug_or_id="abc"))["target"] == "Title (abc)"
    mode["value"] = "yolo"
    assert await fn(MagicMock(), slug_or_id="abc") == {"done": True}
    assert await fn(MagicMock(), slug_or_id="abc", confirm=True) == {"done": True}
    assert calls == ["abc"]


def test_guarded_rejects_tool_without_confirm_param():
    """Decoration-time contract: a destructive tool that forgets to
    declare `confirm` would silently lose the per-call override from its
    inputSchema, so fail fast at import instead."""
    with pytest.raises(TypeError, match="confirm"):

        @guarded("delete", target="abc")
        async def fn(ctx, slug_or_id: str) -> dict:
            return {}


@pytest.mark.asyncio
async def test_guarded_explicit_confirm_false_raises_structured_tool_error(monkeypatch):
    """Refusal from the gate must surface as a ToolError with the JSON
    payload (code + hint), not a bare ICSError: `map_ics_errors` sits
    below the guard and never sees it."""
    from fastmcp.exceptions import ToolError

    monkeypatch.setattr("ics_mcp._helpers.get_mode", lambda ctx: "interactive")

    @guarded("delete", target="abc")
    async def fn(ctx, slug_or_id: str, confirm: bool | None = None) -> dict:
        return {"ran": True}

    ctx = MagicMock()
    with pytest.raises(ToolError) as exc:
        await fn(ctx, slug_or_id="abc", confirm=False)
    assert "confirm_required" in str(exc.value)


# ============================================================
#  upload_files
# ============================================================


async def _build(ctx, files, **kwargs):
    """Run upload_files with a send() that just returns what it was given."""

    async def send(mp, paths):
        return mp, paths

    return await upload_files(ctx, files, send, **kwargs)


@pytest.mark.asyncio
async def test_upload_files_collection_files_emits_paths_and_files():
    ctx = FakeContext()
    files = [
        _StubCollectionFile(path="a/b.md", content="# A"),
        _StubCollectionFile(path="c.md", content="# C"),
    ]
    files_part, paths_part = await _build(ctx, files, message="upload")
    assert len(files_part) == 2
    assert paths_part == ["a/b.md", "c.md"]
    # Basename, payload, mime
    assert files_part[0][1][0] == "b.md"
    assert files_part[0][1][1] == b"# A"
    assert files_part[0][1][2] == "text/markdown"


@pytest.mark.asyncio
async def test_upload_files_collection_with_content_path(tmp_path):
    f = tmp_path / "vault.md"
    f.write_bytes(b"# from disk")
    ctx = FakeContext()
    files = [_StubCollectionFile(path="vault/a.md", content_path=str(f))]
    files_part, _paths = await _build(ctx, files, message="upload")
    assert files_part[0][1][1] == b"# from disk"


@pytest.mark.asyncio
async def test_upload_files_html_with_content_path(tmp_path):
    f = tmp_path / "page.html"
    f.write_bytes(b"<!doctype html><h1>hi</h1>")
    ctx = FakeContext()
    files = [_StubHtmlFile(path="index.html", content_path=str(f), mime="text/html")]
    files_part, _paths = await _build(ctx, files, default_mime="application/octet-stream")
    assert files_part[0][1][1] == b"<!doctype html><h1>hi</h1>"
    assert files_part[0][1][2] == "text/html"


@pytest.mark.asyncio
async def test_upload_files_html_files_with_base64():
    ctx = FakeContext()
    files = [
        _StubHtmlFile(path="index.html", content_text="<html/>"),
        _StubHtmlFile(
            path="data.bin",
            content_base64=base64.b64encode(b"\x00\x01\x02").decode(),
            mime="application/octet-stream",
        ),
    ]
    files_part, _paths = await _build(ctx, files, default_mime="application/octet-stream")
    assert files_part[0][1][1] == b"<html/>"
    assert files_part[1][1][1] == b"\x00\x01\x02"
    assert files_part[1][1][2] == "application/octet-stream"


# ============================================================
#  html_file_for_json
# ============================================================


def _as_json(f):
    from ics_mcp._uploads import html_file_for_json, read_capped

    ((_, raw),) = read_capped([f])
    return html_file_for_json(f, raw)


def test_html_file_for_json_text_passthrough():
    f = _StubHtmlFile(path="index.html", content_text="<html/>", mime="text/html")
    out = _as_json(f)
    assert out == {"path": "index.html", "mime": "text/html", "content_text": "<html/>"}


def test_html_file_for_json_from_path_text(tmp_path):
    p = tmp_path / "x.html"
    p.write_text("<h1>from disk</h1>", encoding="utf-8")
    f = _StubHtmlFile(path="index.html", content_path=str(p), mime="text/html")
    out = _as_json(f)
    assert out["content_text"] == "<h1>from disk</h1>"
    assert "content_path" not in out
    assert "content_base64" not in out


# ============================================================
#  Pydantic XOR validation of content_* (HtmlFile/CollectionFile/CreateMdIn)
# ============================================================


def test_htmlfile_validator_accepts_text_only():
    from ics_mcp.models import HtmlFile

    HtmlFile(path="a.html", content_text="<h1/>")  # does not raise


def test_htmlfile_validator_accepts_path_only(tmp_path):
    from ics_mcp.models import HtmlFile

    HtmlFile(path="a.html", content_path=str(tmp_path / "x.html"))


def test_htmlfile_validator_rejects_two_fields():
    import pydantic

    from ics_mcp.models import HtmlFile

    with pytest.raises(pydantic.ValidationError):
        HtmlFile(path="a.html", content_text="x", content_base64="eA==")


def test_htmlfile_validator_rejects_none():
    import pydantic

    from ics_mcp.models import HtmlFile

    with pytest.raises(pydantic.ValidationError):
        HtmlFile(path="a.html")


def test_collectionfile_validator_accepts_content_only():
    from ics_mcp.models import CollectionFile

    CollectionFile(path="x.md", content="# x")


def test_collectionfile_validator_rejects_both():
    import pydantic

    from ics_mcp.models import CollectionFile

    with pytest.raises(pydantic.ValidationError):
        CollectionFile(path="x.md", content="# x", content_path="/tmp/x")


def test_createmdin_validator_rejects_none():
    import pydantic

    from ics_mcp.models import CreateMdIn

    with pytest.raises(pydantic.ValidationError):
        CreateMdIn(title="t")


def test_createmdin_validator_accepts_content():
    from ics_mcp.models import CreateMdIn

    CreateMdIn(title="t", content="x")


def test_html_file_for_json_from_path_binary(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01\x02")
    f = _StubHtmlFile(path="img.png", content_path=str(p), mime="image/png")
    out = _as_json(f)
    assert "content_text" not in out
    assert "content_base64" in out
    import base64 as b64

    assert b64.b64decode(out["content_base64"]) == b"\x89PNG\r\n\x1a\n\x00\x01\x02"


@pytest.mark.asyncio
async def test_oversized_content_path_is_rejected_before_reading(tmp_path, monkeypatch):
    from pathlib import Path

    from ics_mcp.config import get_settings

    monkeypatch.setattr(get_settings(), "mcp_max_upload_bytes", 10)
    big = tmp_path / "big.md"
    big.write_bytes(b"x" * 100)
    reads = {"n": 0}
    real_read = Path.read_bytes

    def counting(self):
        reads["n"] += 1
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", counting)
    with pytest.raises(ToolError) as exc:
        await _build(FakeContext(), [_StubCollectionFile(path="big.md", content_path=str(big))])
    assert "payload_too_large" in str(exc.value)
    assert reads["n"] == 0


@pytest.mark.asyncio
async def test_total_size_and_file_count_are_capped(monkeypatch):
    from ics_mcp.config import get_settings

    monkeypatch.setattr(get_settings(), "mcp_max_upload_bytes", 5)
    files = [
        _StubCollectionFile(path="a.md", content="abc"),
        _StubCollectionFile(path="b.md", content="abc"),
    ]
    with pytest.raises(ToolError) as exc:
        await _build(FakeContext(), files)
    assert "payload_too_large" in str(exc.value)

    monkeypatch.setattr(get_settings(), "mcp_max_upload_bytes", 1000)
    monkeypatch.setattr(get_settings(), "mcp_max_upload_files", 1)
    with pytest.raises(ToolError) as exc:
        await _build(FakeContext(), files)
    assert "payload_too_large" in str(exc.value)


@pytest.mark.asyncio
async def test_completion_is_reported_after_the_request():
    events: list[str] = []

    class RecordingContext(FakeContext):
        async def report_progress(self, **kwargs):
            if kwargs.get("progress") == kwargs.get("total"):
                events.append("complete")

    async def send(mp, paths):
        events.append("sent")
        return "ok"

    files = [_StubCollectionFile(path="a.md", content="# a")]
    assert await upload_files(RecordingContext(), files, send) == "ok"
    assert events.index("sent") < events.index("complete")


@pytest.mark.asyncio
async def test_failed_upload_is_not_reported_as_complete():
    events: list[str] = []

    class RecordingContext(FakeContext):
        async def report_progress(self, **kwargs):
            if kwargs.get("progress") == kwargs.get("total"):
                events.append("complete")

    async def send(mp, paths):
        raise RuntimeError("network")

    with pytest.raises(RuntimeError):
        await upload_files(
            RecordingContext(), [_StubCollectionFile(path="a.md", content="x")], send
        )
    assert events == []
