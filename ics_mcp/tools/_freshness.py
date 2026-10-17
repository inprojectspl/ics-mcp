"""Freshness signals (ICS ADR-0015) in the outline and read tools."""

from __future__ import annotations

from typing import Any


def successor_notice(
    freshness: str | None, superseded_by: dict[str, Any] | None, latest: str | None = None
) -> str | None:
    """Instruction for the agent when the document is superseded, else None.
    Points at `latest` (the end of the chain) when the direct successor is
    itself superseded."""
    if freshness != "superseded":
        return None
    if not superseded_by or not superseded_by.get("slug"):
        if latest:
            return f"This document is superseded; the current version is `{latest}`."
        return "This document is superseded by a newer one: verify it before relying on it."
    slug = superseded_by["slug"]
    title = superseded_by.get("title") or slug
    if latest and latest != slug:
        return (
            f"This document is superseded by {title!r} (slug `{slug}`), which is superseded "
            f"too; the current version is `{latest}`. Read that one; this one only for history."
        )
    return (
        f"This document is superseded by {title!r} (slug `{slug}`). "
        "Prefer the successor; read this one only for its history."
    )
