"""Keep searchable hits and a continuation when an MCP response is capped."""

from __future__ import annotations

from typing import Any

from ics_mcp._payload import fit_count


def fit_search_page(page: dict[str, Any], offset: int, *, full: bool) -> dict[str, Any]:
    items = list(page.get("items") or [])
    has_more = bool(page.get("has_more") if full else page.get("next_offset") is not None)

    def build(count: int) -> dict[str, Any]:
        cut = count < len(items)
        more = cut or has_more
        result = {**page, "items": items[:count]}
        if full:
            result["has_more"] = more
        if more:
            result["next_offset"] = offset + count
        else:
            result.pop("next_offset", None)
        if cut:
            result.update(
                truncated=True, hint="Page cut to the response limit; continue with `next_offset`."
            )
        return result

    count = fit_count(len(items), build)
    if not count and items:
        # An unusually large hit still needs an identity and forward progress.
        # The document itself is available through the ordinary read tools.
        first = items[0]
        items[0] = {k: first[k] for k in ("slug", "id", "kind", "score") if k in first}
        items[0]["title"] = str(first.get("title") or first.get("slug") or "")[:160]
        result = build(1)
        result.update(truncated=True, hint="Hit shortened to the response limit; read it by slug.")
        return result
    return build(count)
