"""What a relation write changes, in words a human can check in a confirm
prompt or a dry-run preview: titles and slugs instead of bare UUIDs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastmcp import Context

from ics_mcp import session as session_mod
from ics_mcp._helpers import resolve_id, session_key
from ics_mcp._runtime import runtime
from ics_mcp.errors import ICSError


async def describe_asset(slug_or_id: str) -> str:
    """`'Title' (slug)` of an asset, or the input when it cannot be read (the
    write itself then reports the real error)."""
    try:
        _, meta = await resolve_id(slug_or_id)
    except ICSError:
        return slug_or_id
    slug = meta.get("slug") or slug_or_id
    title = meta.get("title")
    return f"{title!r} ({slug})" if title else str(slug)


def _target_suffix(target_path: str | None, target_anchor: str | None) -> str:
    return (f"/{target_path}" if target_path else "") + (
        f"#{target_anchor}" if target_anchor else ""
    )


async def describe_new_relation(
    *,
    source: str,
    target: str,
    relation_type: str,
    target_path: str | None = None,
    target_anchor: str | None = None,
    **_: Any,
) -> str:
    """Target text of `ics_relation_add`: `'A' (a) derived_from 'B' (b)#anchor`."""
    src = await describe_asset(source)
    tgt = await describe_asset(target)
    return f"{src} {relation_type} {tgt}{_target_suffix(target_path, target_anchor)}"


def compact_edge_label(data: Any) -> str | None:
    """`'A' (a) derived_from 'B' (b)#anchor` of one compact edge (ICS
    `GET /api/relations/{id}` and relation writes with `shape=compact`)."""
    if not isinstance(data, Mapping):
        return None
    edge = data.get("edge")
    if not isinstance(edge, list) or len(edge) < 3:
        return None
    nodes = data.get("nodes") if isinstance(data.get("nodes"), Mapping) else {}
    extra = edge[3] if len(edge) > 3 and isinstance(edge[3], Mapping) else {}

    def name(slug: Any) -> str:
        node = nodes.get(slug) if isinstance(nodes, Mapping) else None
        title = node.get("title") if isinstance(node, Mapping) else None
        return f"{title!r} ({slug})" if title else str(slug)

    suffix = _target_suffix(extra.get("target_path"), extra.get("target_anchor"))
    return f"{name(edge[0])} {edge[1]} {name(edge[2])}{suffix}"


async def describe_relation(*, ctx: Context, relation_id: Any, **_: Any) -> str:
    """Target text of `ics_relation_remove`: the ends read from ICS by id,
    else from the relations this session saw."""
    try:
        label = compact_edge_label(
            await runtime.require_ics().get_json(f"/api/relations/{relation_id}")
        )
    except ICSError:
        label = None
    label = label or session_mod.state_for(session_key(ctx)).relation_label(str(relation_id))
    if label:
        return f"relation {relation_id}: {label}"
    return (
        f"relation {relation_id} (its ends are unknown here: list them with "
        "`ics_asset_relations` before confirming)"
    )


def remember_relations(ctx: Context, slug: str, data: Mapping[str, Any]) -> None:
    """Record `<source> <type> <target>` of every edge in an ICS relations
    listing of the asset `slug`, keyed by relation id. Takes the compact
    shape (`[from, type, to, {id, ...}]` by slug) and the full one."""
    state = session_mod.state_for(session_key(ctx))
    for edge in data.get("edges") or []:
        if isinstance(edge, list) and len(edge) >= 4 and isinstance(edge[3], dict):
            extra = edge[3]
            if extra.get("id"):
                suffix = _target_suffix(extra.get("target_path"), extra.get("target_anchor"))
                state.remember_relation(str(extra["id"]), f"{edge[0]} {edge[1]} {edge[2]}{suffix}")
    names = {str(data.get("asset_id")): slug}
    for side in ("outgoing", "incoming"):
        for items in (data.get(side) or {}).values():
            for edge in items or []:
                other = edge.get("other") or {}
                if other.get("id"):
                    names[str(other["id"])] = str(other.get("slug") or other["id"])
                src = names.get(str(edge.get("source_id")), str(edge.get("source_id")))
                tgt = names.get(str(edge.get("target_id")), str(edge.get("target_id")))
                suffix = _target_suffix(edge.get("target_path"), edge.get("target_anchor"))
                if edge.get("id"):
                    state.remember_relation(
                        str(edge["id"]), f"{src} {edge.get('relation_type')} {tgt}{suffix}"
                    )


def remember_new_relation(ctx: Context, data: Mapping[str, Any], source: str, target: str) -> None:
    """Record the relation a write returned (compact shape, or the full one
    from an older ICS)."""
    edge = data.get("edge")
    if isinstance(edge, list) and len(edge) >= 4 and isinstance(edge[3], Mapping):
        label = compact_edge_label(data)
        if edge[3].get("id") and label:
            session_mod.state_for(session_key(ctx)).remember_relation(str(edge[3]["id"]), label)
        return
    if data.get("id"):
        suffix = _target_suffix(data.get("target_path"), data.get("target_anchor"))
        session_mod.state_for(session_key(ctx)).remember_relation(
            str(data["id"]), f"{source} {data.get('relation_type')} {target}{suffix}"
        )
