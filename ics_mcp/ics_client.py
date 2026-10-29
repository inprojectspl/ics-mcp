"""HTTP client that calls ICS in the user's name: one `httpx.AsyncClient` per
process, the Bearer token from TokenStore, one refresh on 401, `Retry-After`
on 429 and exponential backoff on 5xx. ICS errors become structured
`ICSError`s."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, cast

import httpx
from fastmcp.server.dependencies import get_access_token, get_http_request

from ics_mcp.auth.refresh import refresh_token_grant
from ics_mcp.auth.refresh_lock import refresh_lock
from ics_mcp.auth.stdio_oauth import login as stdio_login
from ics_mcp.auth.token_store import TokenPair, TokenStore
from ics_mcp.config import Settings
from ics_mcp.errors import ICSError
from ics_mcp.logging import get_logger

log = get_logger(__name__)

# A gateway 5xx can arrive after ICS already applied the request, so only
# methods that are safe to repeat are retried. PUT is left out on purpose:
# a content PUT creates a new asset version every time it lands.
_RETRY_5XX_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


# Identifiers (slugs, ids, tokens) are interpolated into request paths. A
# dot segment would be normalised by httpx into another endpoint, and `?` or
# `#` would inject a query or fragment, so such paths never leave the client.
_UNSAFE_PATH_CHARS = re.compile(r"[?#\\]|%2e|%2f|%5c", re.IGNORECASE)


#: Request parts FastAPI puts first in a validation error's `loc`.
_LOC_PARTS = frozenset({"body", "query", "path", "header", "form"})


def _validation_error(errors: list[Any], status: int) -> ICSError:
    """ICS request validation (FastAPI 422) as `invalid_argument`, the code of
    every other bad argument, with the first failed field."""
    first = errors[0] if errors and isinstance(errors[0], dict) else {}
    loc = [str(p) for p in first.get("loc") or [] if str(p) not in _LOC_PARTS]
    field = ".".join(loc) or None
    msg = str(first.get("msg") or "invalid value")
    return ICSError(
        "invalid_argument",
        f"Invalid `{field}`: {msg}." if field else f"Invalid request: {msg}.",
        status=status,
        field=field,
        data={"errors": len(errors)} if len(errors) > 1 else None,
    )


def checked_path(path: str) -> str:
    """Return `path` unchanged if it is a plain API path, else raise invalid_argument."""
    segments = path.split("/")
    if (
        not path.startswith("/")
        or _UNSAFE_PATH_CHARS.search(path)
        or any(seg in {".", ".."} for seg in segments)
    ):
        raise ICSError(
            "invalid_argument",
            "Invalid identifier in the request path.",
            hint="Pass the asset slug or id as returned by ics_assets_list.",
            status=400,
        )
    return path


def _retry_after_seconds(value: str | None) -> float:
    """`Retry-After` is either delta-seconds or an HTTP-date (RFC 9110)."""
    if not value:
        return 1.0
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return 1.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - datetime.now(UTC)).total_seconds(), 0.0)


def _over_http() -> bool:
    try:
        get_http_request()
    except RuntimeError:
        return False
    return True


class ICSClient:
    def __init__(self, settings: Settings, store: TokenStore, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.store = store
        self.http = http
        self._lock = asyncio.Lock()

    # -------------------- token management --------------------

    async def _ensure_token(self) -> TokenPair:
        pair = self.store.load()
        if pair and not pair.is_expired():
            return pair
        async with self._lock:
            # Another process may have rotated the pair; decide on fresh data.
            pair = self.store.load_fresh()
            if pair and not pair.is_expired():
                return pair
            if pair:  # try refresh first
                async with refresh_lock(self.store.lock_path):
                    # The previous holder may be another process that just
                    # rotated the pair; its refresh token is spent.
                    pair = self.store.load_fresh()
                    if pair and not pair.is_expired():
                        return pair
                    if pair:
                        try:
                            return await refresh_token_grant(
                                self.settings, self.store, pair, http=self.http
                            )
                        except ICSError as e:
                            log.warning(
                                "refresh failed; falling back to interactive login", code=e.code
                            )
            if self.settings.mcp_transport != "stdio":
                # In HTTP mode the *client* must reauth; we can't open a
                # browser server-side.
                raise ICSError(
                    "auth_required",
                    "No valid token; the MCP client must run the OAuth flow.",
                    status=401,
                )
            return await stdio_login(self.settings, self.store)

    async def _bearer(self) -> str:
        """Token for the outgoing call. Over HTTP every request carries the
        caller's own ICS token (verified by the transport's auth layer), so
        each client acts as itself; stdio uses the locally stored pair."""
        if self.settings.mcp_transport == "http":
            incoming = get_access_token()
            if incoming is None:
                raise ICSError(
                    "auth_required",
                    "The MCP request carried no bearer token.",
                    status=401,
                )
            return incoming.token
        if _over_http():
            # A stdio server exposed by some HTTP runner: the stored tokens
            # belong to this process's user, never to a remote caller.
            raise ICSError(
                "auth_required",
                "This server is configured for stdio; serve HTTP with ICS_MCP_TRANSPORT=http.",
                status=401,
            )
        return (await self._ensure_token()).access_token

    async def _refresh_after_challenge(self, rejected_access_token: str) -> None:
        """Refresh after ICS rejected `rejected_access_token` with a Bearer
        challenge. The stored pair is kept until refresh itself fails, so the
        next `_ensure_token` still has a refresh token to work with."""
        async with self._lock, refresh_lock(self.store.lock_path):
            pair = self.store.load_fresh()
            if pair is None:
                return
            if pair.access_token != rejected_access_token:
                # A concurrent request or process already rotated the pair;
                # refreshing again would replay a used refresh token and trip
                # reuse detection on the server.
                return
            try:
                await refresh_token_grant(self.settings, self.store, pair, http=self.http)
            except ICSError as e:
                latest = self.store.load_fresh()
                if latest is not None and latest.refresh_token != pair.refresh_token:
                    return  # rotated meanwhile (the lock wait timed out): keep it
                log.warning("refresh after 401 failed; dropping stored token", code=e.code)
                self.store.delete()

    async def whoami(self) -> dict[str, Any]:
        return cast(dict[str, Any], await self.get_json("/api/auth/oauth/me"))

    # -------------------- HTTP plumbing --------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        data: Any = None,
        files: Any = None,
        accept: str | None = None,
        attempt: int = 0,
    ) -> httpx.Response:
        checked_path(path)
        access_token = await self._bearer()
        headers = {"Authorization": f"Bearer {access_token}"}
        if accept:
            headers["Accept"] = accept
        url = f"{self.settings.base_url.rstrip('/')}{path}"
        try:
            resp = await self.http.request(
                method, url, json=json_body, params=params, data=data, files=files, headers=headers
            )
        except httpx.HTTPError as e:
            raise ICSError(
                "ics_unreachable",
                f"Cannot connect to ICS: {type(e).__name__}",
                hint="Check ICS_BASE_URL and the network.",
                status=502,
            ) from e

        # 401 -> one-time refresh + retry, but only for a Bearer challenge
        # (`WWW-Authenticate`, RFC 6750). Application-level 401s (e.g. a
        # password-protected share in `POST /share/{token}/resolve`) must
        # neither wipe the stored token nor (in stdio) start an interactive
        # browser login.
        if resp.status_code == 401 and "www-authenticate" in resp.headers:
            if self.settings.mcp_transport == "http":
                # The remote client owns its token and must refresh it.
                raise ICSError("auth_required", "ICS rejected the caller's token.", status=401)
        if resp.status_code == 401 and attempt == 0 and "www-authenticate" in resp.headers:
            log.info("ics returned 401, attempting refresh")
            await self._refresh_after_challenge(access_token)
            return await self._request(
                method,
                path,
                json_body=json_body,
                params=params,
                data=data,
                files=files,
                accept=accept,
                attempt=attempt + 1,
            )
        if resp.status_code == 429 and attempt < 3:
            retry_after = _retry_after_seconds(resp.headers.get("retry-after"))
            await asyncio.sleep(min(retry_after, 30))
            return await self._request(
                method,
                path,
                json_body=json_body,
                params=params,
                data=data,
                files=files,
                accept=accept,
                attempt=attempt + 1,
            )
        if (
            resp.status_code in {502, 503, 504}
            and attempt < 3
            and method.upper() in _RETRY_5XX_METHODS
        ):
            await asyncio.sleep(0.25 * (4**attempt))
            return await self._request(
                method,
                path,
                json_body=json_body,
                params=params,
                data=data,
                files=files,
                accept=accept,
                attempt=attempt + 1,
            )
        if resp.status_code >= 400:
            raise self._map_error(resp)
        return resp

    def _map_error(self, resp: httpx.Response) -> ICSError:
        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError):
            body = {"detail": resp.text}
        body = body if isinstance(body, dict) else {}
        detail = body.get("detail")
        code_guess = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            410: "gone",
            413: "payload_too_large",
            415: "unsupported_media_type",
            422: "invalid_argument",
            429: "rate_limited",
            500: "server_error",
        }.get(resp.status_code, "ics_error")
        # ICS names every error with a stable `code` (and the offending
        # `field`); the agent reacts to that code, so it goes on top and the
        # status-based guess is only a fallback. `data` keeps the rest of the
        # body without repeating what is already on top.
        code = body.get("code")
        field = body.get("field")
        if code == "validation_error" and isinstance(detail, list):
            return _validation_error(detail, resp.status_code)
        return ICSError(
            code if isinstance(code, str) and code else code_guess,
            str(detail) if detail else f"ICS {resp.status_code}",
            status=resp.status_code,
            field=field if isinstance(field, str) else None,
            data={k: v for k, v in body.items() if k not in {"detail", "code", "field"}},
        )

    # -------------------- convenience wrappers --------------------

    async def get_json(self, path: str, **kwargs: Any) -> Any:
        resp = await self._request("GET", path, **kwargs)
        if resp.status_code == 304:
            return {"_not_modified": True}
        return resp.json()

    async def post_json(self, path: str, body: Any = None, **kwargs: Any) -> dict[str, Any]:
        resp = await self._request("POST", path, json_body=body, **kwargs)
        return cast(dict[str, Any], resp.json()) if resp.content else {}

    async def put_json(self, path: str, body: Any = None, **kwargs: Any) -> dict[str, Any]:
        resp = await self._request("PUT", path, json_body=body, **kwargs)
        return cast(dict[str, Any], resp.json()) if resp.content else {}

    async def patch_json(self, path: str, body: Any = None, **kwargs: Any) -> dict[str, Any]:
        resp = await self._request("PATCH", path, json_body=body, **kwargs)
        return cast(dict[str, Any], resp.json()) if resp.content else {}

    async def delete_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = await self._request("DELETE", path, **kwargs)
        if resp.status_code == 204 or not resp.content:
            return {"deleted": True}
        return cast(dict[str, Any], resp.json())

    async def post_multipart(
        self,
        path: str,
        *,
        files: list[tuple[str, tuple[str, bytes, str]]],
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resp = await self._request("POST", path, data=data, files=files, params=params)
        return cast(dict[str, Any], resp.json()) if resp.content else {}


def build_http_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=5.0,
            read=settings.mcp_http_timeout_read,
            write=settings.mcp_http_timeout_write,
            pool=5.0,
        ),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        http2=True,
    )
