"""Hints for the ICS document metadata errors (ICS ADR-0015): `doc_type_unknown`
and `metadata_invalid` come back as a plain 400, so tools that send metadata
pass `METADATA_HINTS` to `map_ics_errors`."""

from __future__ import annotations

from collections.abc import Mapping

METADATA_HINTS: Mapping[str, str] = {
    "doc_type_unknown": "Call `ics_doc_types` for the valid, non-archived keys.",
    "metadata_invalid": (
        "Fix the value named in `field` (summary length, language tag such as "
        "'en' or 'pl-PL', properties matching the document type)."
    ),
}


def create_metadata_fields(doc_type: str | None, summary: str | None) -> dict[str, str]:
    """The optional `doc_type` / `summary` fields of the ICS create endpoints."""
    fields: dict[str, str] = {}
    if doc_type:
        fields["doc_type"] = doc_type
    if summary:
        fields["summary"] = summary
    return fields
