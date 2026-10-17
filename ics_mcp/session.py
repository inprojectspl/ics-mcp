"""Per-connection session state: confirm mode and small caches. LRU-bounded
(`ICS_MCP_SESSION_CACHE_MAX`, default 10 000) so session churn on HTTP cannot
grow memory without limit."""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from ics_mcp.config import ConfirmMode, get_settings

# Slug -> id resolutions are cached for 60s, so an agent looping on the same
# asset (read -> edit -> share -> ...) saves N-1 ICS round-trips. Bounded per
# session so a single rogue client can't exhaust process memory.
_SLUG_CACHE_TTL = 60.0
_SLUG_CACHE_MAX = 256

# Outline cache: same TTL, smaller cap, because an entry holds a whole outline
# (typically 5-50 KB).
_OUTLINE_CACHE_TTL = 60.0
_OUTLINE_CACHE_MAX = 32

# Relation labels seen in this session ("<source> <type> <target>"): ICS has
# no read of one relation by id, so the confirm prompt of a removal names the
# ends only for relations the agent has listed or added here.
_RELATION_LABELS_MAX = 512


def _lru_touch_or_evict(od: OrderedDict[str, Any], key: str, max_size: int) -> None:
    """Manual LRU step: caller has just inserted/refreshed `key`; we
    promote it to the back and evict the oldest if over capacity."""
    od.move_to_end(key)
    if len(od) > max_size:
        od.popitem(last=False)


@dataclass(slots=True)
class SessionState:
    # `state_for` overrides this default with the configured value
    # (`ICS_MCP_DEFAULT_CONFIRM`); the literal here is only a fallback for
    # direct construction in tests.
    confirm_mode: ConfirmMode = "interactive"
    _slug_to_id: OrderedDict[str, tuple[str, float]] = field(default_factory=OrderedDict)
    _outline: OrderedDict[str, tuple[dict[str, Any], float]] = field(default_factory=OrderedDict)
    _relation_labels: OrderedDict[str, str] = field(default_factory=OrderedDict)

    def remember_relation(self, relation_id: str, label: str) -> None:
        self._relation_labels[relation_id] = label
        _lru_touch_or_evict(self._relation_labels, relation_id, _RELATION_LABELS_MAX)

    def relation_label(self, relation_id: str) -> str | None:
        return self._relation_labels.get(relation_id)

    def cache_slug_id(self, slug: str, asset_id: str) -> None:
        self._slug_to_id[slug] = (asset_id, time.time() + _SLUG_CACHE_TTL)
        _lru_touch_or_evict(self._slug_to_id, slug, _SLUG_CACHE_MAX)

    def get_cached_id(self, slug: str) -> str | None:
        entry = self._slug_to_id.get(slug)
        if entry is None:
            return None
        asset_id, expires_at = entry
        if expires_at < time.time():
            self._slug_to_id.pop(slug, None)
            return None
        self._slug_to_id.move_to_end(slug)
        return asset_id

    def invalidate_slug(self, slug: str) -> None:
        self._slug_to_id.pop(slug, None)
        self._outline.pop(slug, None)

    def cache_outline(self, slug: str, outline: dict[str, Any]) -> None:
        self._outline[slug] = (outline, time.time() + _OUTLINE_CACHE_TTL)
        _lru_touch_or_evict(self._outline, slug, _OUTLINE_CACHE_MAX)

    def get_cached_outline(self, slug: str) -> dict[str, Any] | None:
        entry = self._outline.get(slug)
        if entry is None:
            return None
        outline, expires_at = entry
        if expires_at < time.time():
            self._outline.pop(slug, None)
            return None
        self._outline.move_to_end(slug)
        return outline


_MAX = int(os.environ.get("ICS_MCP_SESSION_CACHE_MAX", "10000"))
_STORE: OrderedDict[str, SessionState] = OrderedDict()


def state_for(key: str) -> SessionState:
    state = _STORE.get(key)
    if state is None:
        # A new session starts in the mode from `ICS_MCP_DEFAULT_CONFIRM`
        # (e.g. `yolo` for headless deployments without elicitation).
        state = SessionState(confirm_mode=get_settings().mcp_default_confirm)
        _STORE[key] = state
        if len(_STORE) > _MAX:
            _STORE.popitem(last=False)
        return state
    # Skip move_to_end when already at the back; saves a deque op on
    # every tool call from a hot single-session agent.
    if next(reversed(_STORE), None) != key:
        _STORE.move_to_end(key)
    return state


def reset(key: str) -> None:
    _STORE.pop(key, None)


def clear_all() -> None:
    """Drop every session (test-only API); production should never need
    this. Available so tests don't have to reach into `_STORE`."""
    _STORE.clear()


def size() -> int:
    return len(_STORE)
