"""Response size budget: measuring payloads and shrinking oversized ones."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ics_mcp.config import get_settings

_TRUNCATION_HINT = (
    "Response over budget: drill down via `ics_asset_outline` "
    "(structure only), `ics_asset_read(lines='N-M')` (partial content), "
    "or `ics_assets_list(cursor=...)` (next page)."
)


def _shape_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Top-level keys with their type and size, so the agent sees what an oversized
    payload held without the bytes."""
    summary: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            summary[key] = {"type": "list", "len": len(value)}
        elif isinstance(value, dict):
            summary[key] = {"type": "dict", "keys": list(value.keys())[:20]}
        elif isinstance(value, str):
            summary[key] = {"type": "str", "len": len(value)}
        else:
            summary[key] = {"type": type(value).__name__}
    return summary


def payload_chars(payload: Any) -> int:
    """Size of `payload` as compact JSON, the measure of every response cap."""
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))


def fit_count(total: int, build: Callable[[int], dict[str, Any]], cap: int | None = None) -> int:
    """Largest `k <= total` whose `build(k)` fits `cap` (default: the response
    limit); unlike `maybe_truncate` the agent keeps the nearest items instead
    of a stub."""
    cap = cap or get_settings().mcp_response_max_chars
    if payload_chars(build(total)) <= cap:
        return total
    lo, hi = 0, total - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if payload_chars(build(mid)) <= cap:
            lo = mid
        else:
            hi = mid - 1
    return lo


def maybe_truncate(
    payload: dict[str, Any], *, max_chars: int | None = None, hint: str | None = None
) -> dict[str, Any]:
    """A stub with the top-level shape and a drill-down hint when `payload` is over
    `max_chars` (default from settings), else `payload` unchanged. `hint` replaces
    the default for tools whose follow-up is not an asset tool (e.g. share
    resolve). `len(repr())` is a cheap upper bound that skips serializing most
    responses."""
    cap = max_chars or get_settings().mcp_response_max_chars
    if len(repr(payload)) <= cap:
        return payload
    size = payload_chars(payload)
    if size <= cap:
        return payload
    return {
        "truncated": True,
        "original_size_chars": size,
        "cap_chars": cap,
        "hint": hint or _TRUNCATION_HINT,
        "shape": _shape_summary(payload),
    }
