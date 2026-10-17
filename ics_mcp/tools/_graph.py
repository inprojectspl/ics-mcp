"""Fitting graph responses to the response limit (ICS ADR-0016, section 10), in
the compact shape (nodes keyed by slug, `[from, type, to]` edges) or the full
one. Both are cut from the far end, never to a stub, and a cut says which call
gets the rest."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ics_mcp._payload import fit_count
from ics_mcp.config import get_settings
from ics_mcp.models import GraphDetail

#: Room per requested node, so the response limit follows `max_nodes` the way
#: the context pack's follows its budget. A compact node with its share of
#: edges is about 300-400 characters; a verbose one about three times that.
NODE_CHARS: dict[str, int] = {"compact": 450, "full": 1300}
#: Ceiling of a graph response however many nodes are asked for.
MAX_GRAPH_CHARS = 40_000


def graph_cap(max_nodes: int, detail: GraphDetail) -> int:
    """Response limit of a neighbourhood asked for `max_nodes` nodes."""
    wanted = min(max_nodes * NODE_CHARS[detail], MAX_GRAPH_CHARS)
    return max(get_settings().mcp_response_max_chars, wanted)


def _edge_ends(edge: Any) -> tuple[Any, Any]:
    if isinstance(edge, list):
        return (edge[0], edge[2]) if len(edge) >= 3 else (None, None)
    if isinstance(edge, dict):
        return edge.get("source_id"), edge.get("target_id")
    return None, None


def _edge_type(edge: Any) -> str | None:
    if isinstance(edge, list) and len(edge) >= 2:
        return str(edge[1])
    if isinstance(edge, dict):
        return edge.get("relation_type")
    return None


def _node_rows(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """`(key, node)` pairs in ICS order: slug for compact, id for full."""
    nodes = data.get("nodes")
    if isinstance(nodes, dict):
        return [(k, v) for k, v in nodes.items() if isinstance(v, dict)]
    return [(str(n.get("id")), n) for n in nodes or [] if isinstance(n, dict)]


def _seed(kept: list[tuple[str, dict[str, Any]]]) -> str | None:
    """A kept node on the far edge of the result (never the root) whose own
    neighbourhood can be asked for: the place to walk on from."""
    deepest = max((n.get("depth") or 0 for _, n in kept), default=0)
    if not deepest:
        return None
    for key, node in reversed(kept):
        if (node.get("depth") or 0) == deepest and node.get("expandable", True):
            return str(node.get("slug") or key)
    return None


def _fixed_steps(data: dict[str, Any]) -> list[str]:
    """Next steps that do not depend on how many nodes were kept."""
    steps: list[str] = []
    counts = Counter(t for e in data.get("edges") or [] if (t := _edge_type(e)))
    if len(counts) > 1:
        seen = ", ".join(f"{t} x{n}" for t, n in counts.most_common())
        steps.append(f"fewer `types` (here: {seen})")
    if data.get("direction", "both") == "both":
        steps.append("`direction='out'` (what it builds on) or `'in'` (what builds on it)")
    return steps


def next_steps(
    data: dict[str, Any], kept: list[tuple[str, dict[str, Any]]], fixed: list[str]
) -> str:
    """Calls that fit where this one did not, from what the result holds."""
    steps = list(fixed)
    seed = _seed(kept)
    if seed:
        steps.append(f"walk on from `ics_graph_neighbourhood(slug_or_id='{seed}')`")
    if (data.get("depth") or 1) > 1:
        steps.append("a lower `depth`")
    return "; ".join(steps) or "open the nodes you need with `ics_asset_outline`"


def fit_neighbourhood(data: dict[str, Any], cap: int) -> dict[str, Any]:
    """Keep the nearest nodes (ICS orders them by depth) and the edges
    between them until the response fits `cap`."""
    rows = _node_rows(data)
    compact = isinstance(data.get("nodes"), dict)
    edges: list[Any] = data.get("edges") or []
    fixed = _fixed_steps(data)

    def build(k: int) -> dict[str, Any]:
        kept = rows[:k]
        keys = {key for key, _ in kept}
        out: dict[str, Any] = {
            **data,
            "nodes": dict(kept) if compact else [n for _, n in kept],
            "edges": [e for e in edges if set(_edge_ends(e)) <= keys],
        }
        if k < len(rows):
            out.update(
                truncated=True,
                omitted_nodes=len(rows) - k,
                hint=f"Farthest nodes cut to the response limit. Next: {next_steps(data, kept, fixed)}.",
            )
        elif data.get("truncated"):
            out["hint"] = (
                "`max_nodes` cut the result: raise it (max 200) or narrow it. Next: "
                f"{next_steps(data, kept, fixed)}."
            )
        return out

    return _note_skipped(build(fit_count(len(rows), build, cap)))


def _note_skipped(out: dict[str, Any]) -> dict[str, Any]:
    """Name the edges the type filter left out (ICS `skipped`), so an empty
    default neighbourhood does not read as an isolated document."""
    skipped = out.get("skipped")
    if not skipped:
        return out
    note = "Left out by `types`: " + ", ".join(f"{t} x{n}" for t, n in skipped.items()) + "."
    if "references" in skipped:
        note += " Links in the document content are `references`; add them to `types` to follow."
    hint = out.get("hint")
    return {**out, "hint": f"{hint} {note}" if hint else note}


_RELATIONS_HINT = (
    "Relations cut to the response limit: narrow with `types=[...]` or `direction='out'|'in'`."
)


def fit_relations(data: dict[str, Any]) -> dict[str, Any]:
    """Drop edges from the end until it fits: incoming after outgoing. The
    compact node table keeps only the ends of the kept edges."""
    if isinstance(data.get("edges"), list):
        return _fit_compact_relations(data)
    flat = [
        (side, label, item)
        for side in ("outgoing", "incoming")
        for label, items in (data.get(side) or {}).items()
        for item in items
    ]

    def build(k: int) -> dict[str, Any]:
        out: dict[str, Any] = {**data, "outgoing": {}, "incoming": {}}
        for side, label, item in flat[:k]:
            out[side].setdefault(label, []).append(item)
        if k < len(flat):
            out.update(truncated=True, omitted_edges=len(flat) - k, hint=_RELATIONS_HINT)
        return out

    return build(fit_count(len(flat), build))


def _fit_compact_relations(data: dict[str, Any]) -> dict[str, Any]:
    edges: list[Any] = data["edges"]
    nodes: dict[str, Any] = data.get("nodes") or {}

    def build(k: int) -> dict[str, Any]:
        kept = edges[:k]
        ends = {end for e in kept for end in _edge_ends(e)}
        out = {**data, "nodes": {s: n for s, n in nodes.items() if s in ends}, "edges": kept}
        if k < len(edges):
            out.update(truncated=True, omitted_edges=len(edges) - k, hint=_RELATIONS_HINT)
        return out

    return build(fit_count(len(edges), build))
