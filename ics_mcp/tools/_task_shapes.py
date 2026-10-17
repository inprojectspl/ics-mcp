"""Compact shapes of task links and project links (ICS ADR-0018): documents by
slug and title, without UUIDs other than the link id `ics_task_unlink` takes,
derivable fields, audit fields, defaults and nulls."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ics_mcp.models import successor_slug


def _set(item: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if v is not None and v is not False and v != []}


def asset_name(meta: Mapping[str, Any]) -> dict[str, Any]:
    """`{slug, title}` of a document from its ICS meta."""
    return _set({"slug": meta.get("slug"), "title": meta.get("title")})


def task_ref(raw: Mapping[str, Any]) -> dict[str, Any]:
    """One task link: `id` (for `ics_task_unlink`), the task as the tool
    arguments name it (`wp`, `system` only when not OpenProject, `project`)
    and the link's own fields when set."""
    system = raw.get("system")
    return _set(
        {
            "id": raw.get("id"),
            "wp": raw.get("external_id"),
            "system": None if system == "openproject" else system,
            "project": raw.get("external_scope"),
            "role": raw.get("role"),
            "required": raw.get("required"),
            "label": raw.get("label"),
            "path": raw.get("asset_path"),
            "pinned_version": raw.get("pinned_version"),
            "basis_changed": raw.get("basis_changed"),
            "note": raw.get("note"),
        }
    )


def key_document(raw: Mapping[str, Any]) -> dict[str, Any]:
    """A project key document like a compact list item, plus its `reason`;
    the list order is the reading order, so `position` goes too."""
    kind = raw.get("kind")
    freshness = raw.get("freshness")
    return _set(
        {
            "slug": raw.get("slug"),
            "title": raw.get("title"),
            "kind": None if kind == "md_single" else kind,
            "doc_type": raw.get("doc_type"),
            "freshness": None if freshness == "current" else freshness,
            "summary": raw.get("summary"),
            "estimated_tokens": raw.get("estimated_tokens"),
            "superseded_by": successor_slug(raw.get("superseded_by")),
            "latest": raw.get("latest"),
            "reason": raw.get("reason"),
        }
    )


def project_links(project_slug: str, external: Any, keys: Any) -> dict[str, Any]:
    """`ics_project_links` result: mapped external projects and key documents."""
    return {
        "project_slug": project_slug,
        "external_refs": [_set(r) for r in external or [] if isinstance(r, Mapping)],
        "key_documents": [key_document(d) for d in keys or [] if isinstance(d, Mapping)],
    }
