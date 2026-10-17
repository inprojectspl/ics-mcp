"""Shared helpers used by tool modules: spec-compliant error mapping, slug/id
resolution, session caches and the confirm-flow guard."""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Mapping
from functools import wraps
from typing import Any, NoReturn, ParamSpec, TypeVar, cast, overload
from urllib.parse import urlsplit
from uuid import UUID

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from ics_mcp import session as session_mod
from ics_mcp._runtime import runtime
from ics_mcp.config import ConfirmMode
from ics_mcp.confirm import confirm_or_skip
from ics_mcp.errors import ICSError, raise_tool_error
from ics_mcp.ics_ref import SCHEME, IcsRef, parse_ref
from ics_mcp.logging import get_logger

_log = get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


def err(exc: Exception) -> NoReturn:
    """Translate any exception into a spec-compliant ToolError."""
    if isinstance(exc, ICSError):
        raise_tool_error(exc)
    raise_tool_error(ICSError("internal_error", str(exc)))


def session_key(ctx: Context) -> str:
    try:
        sid = getattr(ctx, "session_id", None) or "stdio"
    except RuntimeError:
        sid = "stdio"
    return f"sid:{sid}"


def get_mode(ctx: Context) -> ConfirmMode:
    return session_mod.state_for(session_key(ctx)).confirm_mode


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def require_uuid(value: str, *, code: str = "id_required", hint: str | None = None) -> str:
    if not _is_uuid(value):
        raise_tool_error(ICSError(code, "An asset UUID is required.", hint=hint))
    return value


# ICS issues tokens with `secrets.token_urlsafe(32)` (43 base64url chars,
# column up to 64). The lower bound of 16 rejects path fragments that cannot
# be a token.
_SHARE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def extract_share_token(share_link: str) -> str:
    """Share token from either a bare token or a pasted share URL
    (`https://.../s/<token>`, optionally with `?m=` or a fragment)."""
    candidate = share_link.strip()
    if "/" in candidate or "?" in candidate or "#" in candidate:
        parts = [p for p in urlsplit(candidate).path.split("/") if p]
        try:
            candidate = parts[parts.index("s") + 1]
        except (ValueError, IndexError):
            raise_tool_error(
                ICSError(
                    "bad_share_link",
                    f"Cannot extract a share-link token from: {share_link}",
                    hint="Expected format: https://<host>/s/<token> or a bare token.",
                )
            )
    if not _SHARE_TOKEN_RE.match(candidate):
        raise_tool_error(
            ICSError(
                "bad_share_link",
                f"This does not look like a share-link token: {candidate}",
                hint="A token is 16-64 characters of [A-Za-z0-9_-] (the segment after /s/ in the URL).",
            )
        )
    return candidate


def parse_asset_ref(value: str) -> IcsRef | None:
    """The parsed `ics://asset/...` reference, or None for a plain slug or id."""
    if not value.startswith(SCHEME):
        return None
    try:
        return parse_ref(value)
    except ValueError as exc:
        raise ICSError(
            "invalid_argument",
            str(exc),
            hint="Pass a slug, an id, or `ics://asset/<slug>[/file/<path>][#<anchor>]`.",
            field="slug_or_id",
        ) from exc


def slug_from(value: str) -> str:
    """A slug or id as given, or the slug of an `ics://asset/...` reference
    (the form outline and relation targets use)."""
    ref = parse_asset_ref(value)
    return ref.slug if ref else value


async def resolve_slug(slug_or_id: str) -> str:
    """Path-safe slug from a slug, a UUID identifier or an `ics://` reference."""
    slug_or_id = slug_from(slug_or_id)
    if not _is_uuid(slug_or_id):
        return slug_or_id
    meta = await runtime.require_ics().get_json(f"/api/assets/{slug_or_id}")
    return cast(str, meta["slug"])


async def resolve_id(slug_or_id: str) -> tuple[str, dict[str, Any]]:
    """`(asset_id, meta)` in one uncached ICS round-trip, for callers that need
    fresh meta; tools that only need the id use `resolve_id_cached`."""
    slug_or_id = slug_from(slug_or_id)
    ics = runtime.require_ics()
    if _is_uuid(slug_or_id):
        meta = await ics.get_json(f"/api/assets/{slug_or_id}")
    else:
        meta = await ics.get_json(f"/api/assets/by-slug/{slug_or_id}/meta")
    return meta["id"], meta


async def resolve_id_cached(ctx: Context, slug_or_id: str) -> str:
    """`slug -> asset_id` through the per-session LRU (TTL 60s); UUIDs pass
    through."""
    slug_or_id = slug_from(slug_or_id)
    if _is_uuid(slug_or_id):
        return slug_or_id
    state = session_mod.state_for(session_key(ctx))
    cached = state.get_cached_id(slug_or_id)
    if cached is not None:
        return cached
    meta = await runtime.require_ics().get_json(f"/api/assets/by-slug/{slug_or_id}/meta")
    state.cache_slug_id(slug_or_id, meta["id"])
    return cast(str, meta["id"])


def invalidate_slug_cache(ctx: Context, slug_or_id: str) -> None:
    """Drop the cached id and outline after an operation that may void them.
    The cache is keyed by slug, so a UUID has nothing to invalidate."""
    if _is_uuid(slug_or_id):
        return
    session_mod.state_for(session_key(ctx)).invalidate_slug(slug_or_id)


def cached_outline(ctx: Context, slug: str) -> dict[str, Any] | None:
    """Return per-session cached outline if fresh, else None."""
    return session_mod.state_for(session_key(ctx)).get_cached_outline(slug)


def store_outline(ctx: Context, slug: str, outline: dict[str, Any]) -> None:
    """Cache an outline for 60s in the per-session LRU."""
    session_mod.state_for(session_key(ctx)).cache_outline(slug, outline)


def drop_none(**values: Any) -> dict[str, Any]:
    """Query params or a JSON body without the arguments left at `None`."""
    return {k: v for k, v in values.items() if v is not None}


def promote_error(e: ICSError, hints: Mapping[str, str]) -> ICSError:
    """`e` with the fix hint `hints` has for its code (else the hint `e`
    already had). The ICS `code` and `field` are already on top of every
    ICS error (`ICSClient._map_error`); errors raised by the tool itself
    (no HTTP status) pass unchanged."""
    hint = hints.get(e.code)
    if e.status is None or hint is None:
        return e
    return ICSError(e.code, e.message, hint=hint, status=e.status, field=e.field, data=e.data)


@overload
def map_ics_errors(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]: ...  # noqa: UP047


@overload
def map_ics_errors(
    *, hints: Mapping[str, str]
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]: ...


def map_ics_errors(  # noqa: UP047 - PEP 695 syntax doesn't accept ParamSpec yet
    fn: Callable[P, Awaitable[T]] | None = None, *, hints: Mapping[str, str] | None = None
) -> Any:
    """Translate errors raised inside the tool into a spec-compliant ToolError;
    `hints=` adds the fix hint for the ICS `code` (`promote_error`)."""
    if fn is None:
        return lambda f: _map_ics_errors(f, hints)
    return _map_ics_errors(fn, hints)


def _map_ics_errors(  # noqa: UP047 - PEP 695 syntax doesn't accept ParamSpec yet
    fn: Callable[P, Awaitable[T]], hints: Mapping[str, str] | None
) -> Callable[P, Awaitable[T]]:
    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except ICSError as e:
            err(promote_error(e, hints) if hints is not None else e)
        except UnicodeDecodeError:
            err(
                ICSError(
                    "invalid_argument",
                    "The file is not UTF-8 text.",
                    hint="Upload binary files as an HTML bundle.",
                )
            )
        except ValidationError as e:
            err(
                ICSError(
                    "unexpected_response",
                    f"Unexpected data shape: {e.error_count()} validation error(s).",
                )
            )
        except Exception as e:
            # Last resort: the model gets a structured error instead of a raw
            # traceback, and the details stay in the server log.
            _log.exception("unhandled error in tool", tool=getattr(fn, "__name__", "?"))
            err(ICSError("internal_error", f"Unexpected {type(e).__name__} in the MCP server."))

    return wrapper


def guarded(
    action: str,
    *,
    target: str | Callable[..., str | Awaitable[str]],
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[Any]]]:
    """Wrap a destructive tool with the confirm-flow gate.

    `target` (a string, or a sync/async callable of the tool kwargs plus
    `ctx`) describes the change for the prompt and the dry-run preview; it is
    only evaluated when someone will read it, so it may afford an ICS lookup.
    The tool must declare `confirm: M.ConfirmFlag = None`, since FastMCP
    builds the inputSchema from the signature; this is checked at import."""

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[Any]]:
        if "confirm" not in inspect.signature(fn).parameters:
            raise TypeError(
                f"@guarded tool {fn.__name__!r} must declare "
                "`confirm: M.ConfirmFlag = None`; without it the per-call "
                "override is absent from the MCP inputSchema."
            )

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx: Context = args[0] if args else kwargs["ctx"]
            confirm = kwargs.pop("confirm", None)
            mode = get_mode(ctx)
            if confirm is True or (confirm is None and mode == "yolo"):
                return await fn(*args, **kwargs)
            try:
                if callable(target):
                    described = target(**{**kwargs, "ctx": ctx})
                    tgt = await described if inspect.isawaitable(described) else described
                else:
                    tgt = target
                preview = await confirm_or_skip(
                    ctx,
                    action=action,
                    target=tgt,
                    confirm=confirm,
                    mode=mode,
                )
            except ICSError as e:
                # `map_ics_errors` sits below the guard, so a refusal/decline
                # from the gate has to be mapped here; otherwise the client
                # gets a bare exception instead of a structured ToolError.
                err(e)
            if preview is not None:
                return preview
            return await fn(*args, **kwargs)

        return wrapper

    return decorator
