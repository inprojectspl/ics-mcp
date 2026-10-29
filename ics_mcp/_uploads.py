"""File contents for uploads: inline text, base64 or a local path (stdio only),
with the upload size and count caps."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from typing import Any, NoReturn, cast

from fastmcp import Context

from ics_mcp.config import get_settings
from ics_mcp.errors import ICSError, raise_tool_error
from ics_mcp.progress import progress_scope


def file_bytes(
    content_text: str | None,
    content_base64: str | None,
    content_path: str | None = None,
) -> bytes:
    """Bytes of exactly one of content_text, content_base64 or content_path.
    `content_path` is read from the user's disk (stdio only), which keeps multi-KB
    files out of tool arguments."""
    import base64

    provided = [v for v in (content_text, content_base64, content_path) if v is not None]
    if not provided:
        raise_tool_error(
            ICSError(
                "invalid_argument",
                "One of content_text, content_base64 or content_path is required.",
                field="content_text",
            )
        )
    if len(provided) > 1:
        raise_tool_error(
            ICSError(
                "invalid_argument",
                "Provide exactly one of content_text/content_base64/content_path.",
                field="content_text",
            )
        )
    if content_path is not None and get_settings().mcp_transport == "http":
        # Over HTTP the path would be read on the server, not on the caller's
        # machine, which exposes server files (including stored tokens).
        raise_tool_error(
            ICSError(
                "invalid_argument",
                "content_path is only available over stdio.",
                field="content_path",
                hint="Send the content inline with content_text or content_base64.",
            )
        )
    if content_text is not None:
        raw = content_text.encode("utf-8")
    elif content_base64 is not None:
        raw = base64.b64decode(content_base64 or "")
    else:
        return _read_local_path(content_path or "")  # checked with stat() before reading
    if len(raw) > get_settings().mcp_max_upload_bytes:
        too_large("The content")
    return raw


def too_large(what: str) -> NoReturn:
    limit = get_settings().mcp_max_upload_bytes
    raise_tool_error(
        ICSError(
            "payload_too_large",
            f"{what} exceeds the upload limit of {limit // (1024 * 1024)} MiB.",
            hint="Split the upload or raise ICS_MCP_MAX_UPLOAD_BYTES (the server has its own cap).",
        )
    )


def _read_local_path(path: str) -> bytes:
    """Read bytes from local filesystem. `~` expands to home. Friendly error
    when the file doesn't exist or isn't readable. The size is checked with
    stat() first, so an oversized file is never loaded."""
    from pathlib import Path

    try:
        p = Path(path).expanduser()
        if p.is_file() and p.stat().st_size > get_settings().mcp_max_upload_bytes:
            too_large(f"content_path {path}")
        return p.read_bytes()
    except FileNotFoundError:
        raise_tool_error(
            ICSError(
                "invalid_argument",
                f"content_path: file does not exist: {path}",
                field="content_path",
            )
        )
    except IsADirectoryError:
        raise_tool_error(
            ICSError(
                "invalid_argument",
                f"content_path: is a directory, not a file: {path}",
                field="content_path",
            )
        )
    except PermissionError:
        raise_tool_error(
            ICSError(
                "invalid_argument",
                f"content_path: no read permission: {path}",
                field="content_path",
            )
        )
    except OSError as e:
        raise_tool_error(
            ICSError(
                "invalid_argument", f"content_path: cannot read ({e}): {path}", field="content_path"
            )
        )


def read_capped(files: list[Any]) -> Iterator[tuple[Any, bytes]]:
    """Each file with its bytes, enforcing the file-count and total-size caps
    before anything is sent: every multi-file upload goes through here."""
    settings = get_settings()
    if len(files) > settings.mcp_max_upload_files:
        raise_tool_error(
            ICSError(
                "payload_too_large",
                f"{len(files)} files exceed the limit of {settings.mcp_max_upload_files}.",
            )
        )
    total = 0
    for f in files:
        raw = _file_raw(f)
        total += len(raw)
        if total > settings.mcp_max_upload_bytes:
            too_large("The upload")
        yield f, raw


async def upload_files[R](
    ctx: Context,
    files: list[Any],
    send: Callable[[list[Any], list[str]], Awaitable[R]],
    *,
    default_mime: str = "text/markdown",
    message: str = "",
) -> R:
    """Read `files`, then call `send(multipart, paths)`, reporting progress
    over both steps: one tick per file read and a final one once ICS has
    answered. Enforces the file-count and total-size caps before sending."""
    async with progress_scope(ctx, total=len(files) + 1, message=message) as tick:
        mp: list[Any] = []
        paths: list[str] = []
        for f, raw in read_capped(files):
            mp.append(("files", (f.path.split("/")[-1], raw, _file_mime(f, default_mime))))
            paths.append(f.path)
            await tick(1, f"+{f.path}")
        result = await send(mp, paths)
        await tick(1, "uploaded")
    return result


def _file_raw(f: Any) -> bytes:
    # CollectionFile: content (inline str) or content_path (path).
    # HtmlFile: content_text/content_base64/content_path.
    if hasattr(f, "content") and f.content is not None:
        if getattr(f, "content_path", None) is not None:
            raise_tool_error(
                ICSError(
                    "invalid_argument",
                    f"{getattr(f, 'path', '<?>')}: provide only one of content/content_path.",
                    field="files",
                )
            )
        return cast(str, f.content).encode("utf-8")
    return file_bytes(
        getattr(f, "content_text", None),
        getattr(f, "content_base64", None),
        getattr(f, "content_path", None),
    )


def _file_mime(f: Any, default: str) -> str:
    return getattr(f, "mime", None) or default


def html_file_for_json(f: Any, raw: bytes) -> dict[str, Any]:
    """`HtmlFile` with its bytes as the dict `/api/assets/html-json` accepts:
    sent as `content_text` when it decodes as UTF-8, else as `content_base64`."""
    out: dict[str, Any] = {"path": f.path}
    if f.mime is not None:
        out["mime"] = f.mime
    try:
        out["content_text"] = raw.decode("utf-8")
    except UnicodeDecodeError:
        import base64

        out["content_base64"] = base64.b64encode(raw).decode("ascii")
    return out
