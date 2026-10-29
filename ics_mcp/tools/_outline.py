"""Outline shaping (ICS ADR-0016, section 10) and the heading lookup behind
`ics_asset_read(anchor=...)`. An outline is never replaced by a stub: over the
limit it loses edge extras and wikilink lists, then the deepest heading
levels, then items past a page (`next_offset`), and edges last."""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from ics_mcp._helpers import store_outline
from ics_mcp._payload import fit_count, payload_chars
from ics_mcp._runtime import runtime
from ics_mcp.config import get_settings
from ics_mcp.errors import ICSError
from ics_mcp.models import successor_slug
from ics_mcp.tools._freshness import successor_notice

#: `ics_asset_outline` answers a building outline with this instead of an
#: error; `ics_asset_read(anchor=...)` cannot resolve one and fails with
#: `outline_building`. Both send the agent to a direct read, not a wait loop.
BUILDING_HINT = (
    "The outline is still being built. Do not wait in a loop: read the file "
    "directly with `ics_asset_read` (`lines='1-200'` for the start), or retry "
    "the outline later."
)

#: Kinds whose outline lists headings at the top; the others list `files`.
_HEADING_KINDS = frozenset({"md_single", "pdf_doc", "office_doc"})
_MAX_LEVEL = 6


def _items_key(data: dict[str, Any]) -> str:
    if data.get("kind") in _HEADING_KINDS or "files" not in data:
        return "headings"
    return "files"


def _level_cut(items: list[Any], level: int) -> list[Any]:
    return [h for h in items if not isinstance(h, dict) or (h.get("level") or 1) <= level]


def _at_level(data: dict[str, Any], level: int) -> dict[str, Any]:
    """`data` without headings (and PDF bookmarks) deeper than `level`."""
    out = dict(data)
    for key in ("headings", "bookmarks"):
        if isinstance(out.get(key), list):
            out[key] = _level_cut(out[key], level)
    if isinstance(out.get("files"), list):
        out["files"] = [
            {**f, "headings": _level_cut(f["headings"], level)}
            if isinstance(f, dict) and isinstance(f.get("headings"), list)
            else f
            for f in out["files"]
        ]
    return out


def _bare(data: dict[str, Any]) -> dict[str, Any]:
    """Edges as plain triples without the node table, files without their
    wikilink lists (the counts stay)."""
    out = {k: v for k, v in data.items() if k != "nodes"}
    if isinstance(out.get("edges"), list):
        out["edges"] = [e[:3] if isinstance(e, list) else e for e in out["edges"]]
    if isinstance(out.get("files"), list):
        out["files"] = [
            {k: v for k, v in f.items() if k != "wikilinks_out"} if isinstance(f, dict) else f
            for f in out["files"]
        ]
    return out


def shape_outline(
    data: dict[str, Any],
    *,
    edges: bool = False,
    max_level: int | None = None,
    offset: int = 0,
    cap: int | None = None,
) -> dict[str, Any]:
    """The outline the agent gets: the successor notice, edges only when
    asked for, headings up to `max_level`, items from `offset`, trimmed
    step by step until it fits `cap`."""
    cap = cap or get_settings().mcp_response_max_chars
    # Nulls and a false `truncated` (ICS's own storage cap) say nothing.
    out = {k: v for k, v in data.items() if v is not None and not (k == "truncated" and v is False)}
    notice = successor_notice(out.get("freshness"), out.get("superseded_by"), out.get("latest"))
    if notice:
        out["notice"] = notice
    if isinstance(out.get("superseded_by"), dict):
        out["superseded_by"] = successor_slug(out["superseded_by"])
    if not edges:
        out.pop("edges", None)
        out.pop("nodes", None)
    if "status" in out:  # still building: nothing to shape
        return {**out, "hint": BUILDING_HINT}
    level = max_level or _MAX_LEVEL
    key = _items_key(out)
    out = _at_level(out, level)
    if isinstance(out.get(key), list) and offset:
        out[key] = out[key][offset:]

    trimmed: dict[str, Any] = {}
    if payload_chars(out) > cap:
        out = _bare(out)
        trimmed["edges"] = "bare"
    while payload_chars(out) > cap and level > 1:
        level -= 1
        out = _at_level(out, level)
        trimmed["max_level"] = level
    items = out.get(key)
    if payload_chars(out) > cap and isinstance(items, list):
        # Room for the `trimmed` note and hint added below.
        base = {**out, "trimmed": trimmed | {"next_offset": 10**6}, "hint": "x" * 640}

        def page(k: int) -> dict[str, Any]:
            return {**base, key: items[:k]}

        k = fit_count(len(items), page, cap)
        if k == 0:
            # The first item alone is over the limit; an empty page would
            # offer the same offset forever, so show what fits of it and move on.
            out[key] = [_partial_item(items[0], base, key, cap, trimmed)]
            k = 1
        else:
            out[key] = items[:k]
        if k < len(items):
            trimmed["next_offset"] = offset + k
    if payload_chars(out) > cap and out.get("edges"):
        trimmed["edges"] = "omitted"
        trimmed["omitted_edges"] = len(out.pop("edges"))
    if trimmed:
        out["trimmed"] = trimmed
        out["hint"] = _trim_hint(trimmed)
    return out


def _partial_item(
    item: Any, base: dict[str, Any], key: str, cap: int, trimmed: dict[str, Any]
) -> Any:
    """A collection file with as many of its headings as fit `cap`."""
    if not isinstance(item, dict) or not isinstance(item.get("headings"), list):
        return item
    heads = item["headings"]
    note = {"path": item.get("path"), "shown": 10**6, "total": len(heads)}

    def page(n: int) -> dict[str, Any]:
        cut = {**base["trimmed"], "file_headings": note}
        return {**base, "trimmed": cut, key: [{**item, "headings": heads[:n]}]}

    n = fit_count(len(heads), page, cap)
    trimmed["file_headings"] = {**note, "shown": n}
    return {**item, "headings": heads[:n]}


def _trim_hint(trimmed: dict[str, Any]) -> str:
    parts = []
    if "file_headings" in trimmed:
        cut = trimmed["file_headings"]
        parts.append(
            f"file {cut['path']!r} shows {cut['shown']} of {cut['total']} headings: read the "
            f"rest with `ics_asset_read(path={cut['path']!r}, lines='N-M')`"
        )
    if "max_level" in trimmed:
        parts.append(
            f"headings deeper than level {trimmed['max_level']} left out: read a section with "
            "`ics_asset_read(anchor=...)` (`end_line` gives its size)"
        )
    if "next_offset" in trimmed:
        parts.append(f"more items follow: call again with `offset={trimmed['next_offset']}`")
    if trimmed.get("edges") == "bare":
        parts.append("edge details left out: `ics_asset_relations` lists them")
    if trimmed.get("edges") == "omitted":
        parts.append("edges left out: `ics_asset_relations` lists them")
    return "Outline trimmed to the response limit; " + "; ".join(parts) + "."


def heading_lines(outline: dict[str, Any], anchor: str, path: str | None) -> tuple[int, int]:
    """`(line, end_line)` of the heading `anchor`, in `path` for a collection
    (default: its entry file). Raises `anchor_not_found` with the anchors
    that do exist."""
    if outline.get("status") == "building":
        raise ICSError(
            "outline_building",
            "The outline is still being built, so the anchor cannot be resolved yet.",
            hint="Read without `anchor` (the whole file or `lines=`), or retry in a few seconds.",
        )
    headings: list[Any] = outline.get("headings") or []
    if outline.get("kind") == "md_collection":
        wanted = path or outline.get("entry_path")
        file = next(
            (
                f
                for f in outline.get("files") or []
                if isinstance(f, dict) and f.get("path") == wanted
            ),
            None,
        )
        headings = (file or {}).get("headings") or []
    for h in headings:
        if isinstance(h, dict) and h.get("anchor") == anchor:
            line = int(h["line"])
            return line, int(h.get("end_line") or line)
    known = ", ".join(str(h.get("anchor")) for h in headings[:20] if isinstance(h, dict))
    raise ICSError(
        "anchor_not_found",
        f"No heading with anchor {anchor!r} in this file.",
        hint=f"Anchors here: {known}." if known else "The file has no headings; read it whole.",
        field="anchor",
    )


async def load_outline(
    ctx: Context, slug: str, *, wait: bool = False, edges: bool = False
) -> dict[str, Any]:
    """The ICS outline, with compact edges only when asked for. Always asked
    of ICS, so a revoked access is not answered from memory; the outline
    without edges is kept to resolve anchors (edges change without a new
    version)."""
    cacheable = not edges
    params: dict[str, str] = {"shape": "compact", "edges": str(edges).lower()}
    if wait:
        params["wait"] = "true"
    data: dict[str, Any] = await runtime.require_ics().get_json(
        f"/api/assets/by-slug/{slug}/outline", params=params
    )
    if cacheable and data.get("status") != "building":
        store_outline(ctx, slug, data)
    return data
