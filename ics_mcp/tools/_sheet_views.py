"""Shaping ICS answers about Google Sheets syncs for an agent: changes keyed
by column header and place, conflicts with their decision keys, lists cut to
the response limit, and the next step (ICS ADR-0031, ADR-0033)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ics_mcp._payload import fit_count, payload_chars
from ics_mcp.config import get_settings

# Lists cut first when a view is over the response limit; conflicts last,
# since each one needs a decision.
_TRIM_ORDER = ("appends", "creates", "exports", "imports", "issues", "conflicts")
_OMITTED_HINT = (
    "Cut to the response limit; `summary` has the full counts and the ICS panel at "
    "`panel_url` the full list."
)
UNCERTAIN_NEXT = (
    "Google's answer to the sheet write was lost, so it is not known whether the cells "
    "were written. Call ics_sheets_status(slug_or_id, operation_id=..., check=True): it "
    "reads the cells back and never writes. Do not call ics_sheets_apply or "
    "ics_sheets_preview to retry the write."
)
RESUME_NEXT = (
    "Call ics_sheets_apply again with the same operation_id and decisions: the operation "
    "resumes where it stopped and never applies twice. Do not preview again."
)
PREVIEW_AGAIN = (
    "This operation can no longer be applied. Call ics_sheets_preview again and show the "
    "user the new changes."
)


def _panel_url(slug: str) -> str:
    return f"{get_settings().issuer}/v/{slug}?tab=sheets"


def _values(values: dict[str, Any], header: Callable[[str], str]) -> dict[str, Any]:
    return {header(f): v for f, v in values.items()}


def _issue(issue: dict[str, Any], header: Callable[[str], str]) -> dict[str, Any]:
    out = dict(issue)
    if "field" in out:
        out["column"] = header(out.pop("field"))
    if "fields" in out:
        out["columns"] = [header(f) for f in out.pop("fields")]
    return out


_PLACE = ("collection", "tab", "row")


def _where(item: dict[str, Any], keys: tuple[str, ...] = (*_PLACE, "record_id")) -> dict[str, Any]:
    """The collection, tab and tab row of a change, as far as it has them."""
    return {k: item[k] for k in keys if item.get(k) is not None}


def _op_next(op: dict[str, Any]) -> str:
    state, google = op.get("state"), op.get("google_status")
    if state == "previewed":
        summary = op.get("summary") or {}
        if not any(summary.get(k) for k in ("imports", "exports", "conflicts")):
            return "Nothing to change; no apply is needed."
        step = (
            "Show the user what changes. Each conflict needs the user's decision: 'app' "
            "keeps the app value and writes it to the sheet, 'sheet' takes the sheet value "
            "into the app. Then ics_sheets_apply(slug_or_id, operation_id, "
            "decisions={key: 'app' | 'sheet'})."
            if summary.get("conflicts")
            else "Show the user what changes, then ics_sheets_apply(slug_or_id, operation_id)."
        )
        if summary.get("issues"):
            step += " Rows in `issues` are skipped until fixed in the sheet."
        return step
    if state == "applying":
        return RESUME_NEXT
    if state == "applied":
        if google == "uncertain":
            return UNCERTAIN_NEXT
        if google == "failed":
            return (
                "The app changes are saved, but the sheet cells were not written "
                f"(`{op.get('error')}`). The next ics_sheets_preview offers them again."
            )
        if google == "pending":
            return (
                "The sheet write has not been confirmed. If this stays so for more than a "
                "minute or two, call ics_sheets_status(slug_or_id, operation_id=..., "
                "check=True): ICS settles it by reading the cells back and never writes."
            )
        return "Done: the app and the sheet agree."
    return PREVIEW_AGAIN


def _noted(omitted: dict[str, int], slug: str) -> dict[str, Any]:
    return {"omitted": omitted, "panel_url": _panel_url(slug), "omitted_hint": _OMITTED_HINT}


def _fitting(view: dict[str, Any], key: str, omitted: dict[str, int], slug: str, cap: int) -> int:
    """How many entries of `view[key]` fit `cap` with the cut noted."""
    items: list[Any] = view[key]

    def build(k: int) -> dict[str, Any]:
        cut = {**omitted, key: len(items) - k} if k < len(items) else omitted
        return {**view, key: items[:k], **_noted(cut, slug)}

    return fit_count(len(items), build, cap)


def _fit(view: dict[str, Any], slug: str) -> dict[str, Any]:
    """`view` under the response limit: lists are cut in `_TRIM_ORDER`."""
    cap = get_settings().mcp_response_max_chars
    omitted: dict[str, int] = {}
    for key in _TRIM_ORDER:
        if payload_chars({**view, **_noted(omitted, slug)} if omitted else view) <= cap:
            break
        items: list[Any] = view.get(key) or []
        if not items:
            continue
        k = _fitting(view, key, omitted, slug, cap)
        view = {**view, key: items[:k]}
        if k < len(items):
            omitted[key] = len(items) - k
    return {**view, **_noted(omitted, slug)} if omitted else view


def op_view(op: dict[str, Any], slug: str) -> dict[str, Any]:
    """An ICS operation compacted for an agent: changes keyed by column
    header, conflicts with the `record_id:field` key a decision takes."""
    out: dict[str, Any] = {
        "operation_id": op.get("id"),
        "state": op.get("state"),
        "google_status": op.get("google_status"),
        "error": op.get("error"),
        "mine": op.get("mine"),
        "created_at": op.get("created_at"),
        "summary": op.get("summary"),
        "result": op.get("result"),
        "auto": op.get("auto"),
    }
    if "updates" in op:
        headers: dict[str, dict[str, str]] = op.get("headers") or {}

        def header_of(collection: str | None) -> Callable[[str], str]:
            own = headers.get(collection or "") or {}
            return lambda field: own.get(field, field)

        imports, exports, conflicts = [], [], []
        for u in op.get("updates") or []:
            where, header = _where(u), header_of(u.get("collection"))
            if u.get("import"):
                imports.append({**where, "values": _values(u["import"], header)})
            if u.get("export"):
                exports.append({**where, "values": _values(u["export"], header)})
            for c in u.get("conflicts") or []:
                conflicts.append(
                    {
                        "key": f"{u['record_id']}:{c['field']}",
                        **_where(u, _PLACE),
                        "column": header(c["field"]),
                        "base": c.get("base"),
                        "app": c.get("app"),
                        "sheet": c.get("sheet"),
                    }
                )
        lists = {
            "conflicts": conflicts,
            "issues": [_issue(i, header_of(i.get("collection"))) for i in op.get("issues") or []],
            "imports": imports,
            "exports": exports,
            "creates": [
                {
                    **_where(c),
                    "values": _values(c.get("data") or {}, header_of(c.get("collection"))),
                }
                for c in op.get("creates") or []
            ],
            "appends": [
                {
                    **_where(a),
                    "values": _values(a.get("values") or {}, header_of(a.get("collection"))),
                }
                for a in op.get("appends") or []
            ],
        }
        out.update({k: v for k, v in lists.items() if v})
        if op.get("decisions"):
            out["decisions"] = op["decisions"]
    out["next"] = _op_next(op)
    return _fit(out, slug)


def _summary(op: dict[str, Any]) -> dict[str, Any]:
    keys = ("state", "google_status", "error", "mine", "created_at", "summary", "auto")
    return {"operation_id": op.get("id"), **{k: op.get(k) for k in keys}}
