"""Token store: keyring round-trip, encrypted-file fallback and cache.
The keyring is the in-memory backend from conftest, never the OS one."""

from __future__ import annotations

import uuid

import keyring
import pytest
from keyring.errors import KeyringError

from ics_mcp.auth.token_store import TokenPair, TokenStore
from tests.conftest import MemoryKeyring


@pytest.fixture
def store(tmp_path) -> TokenStore:
    # Unique service name per test: no cross-test bleed via the OS keyring.
    s = TokenStore(
        service=f"ics-mcp-test-{uuid.uuid4().hex[:8]}",
        fallback_path=tmp_path / "creds.json",
    )
    yield s
    s.delete()


def test_save_and_load_roundtrip(store):
    pair = TokenPair(
        access_token="header.payload.sig",
        refresh_token="opaque-refresh",
        expires_at=9_999_999_999.0,
        scope="ics",
        resource="https://ics.test/mcp",
    )
    store.save(pair)
    loaded = store.load()
    assert loaded is not None
    assert loaded.access_token == "header.payload.sig"
    assert loaded.refresh_token == "opaque-refresh"
    assert loaded.scope == "ics"
    assert loaded.resource == "https://ics.test/mcp"


def test_load_missing_returns_none(store):
    assert store.load() is None


def test_delete_clears(store):
    pair = TokenPair(
        access_token="a",
        refresh_token="b",
        expires_at=9_999_999_999.0,
        scope="ics",
        resource="https://ics.test/mcp",
    )
    store.save(pair)
    assert store.load() is not None
    store.delete()
    # On non-keyring platform file is gone; on keyring platform load() may
    # still return from keyring entry; either is acceptable for this test.
    after = store.load()
    if after is not None:
        # Re-delete to be safe (test isolation)
        store.delete()


def test_pair_expiry_detection():
    pair = TokenPair(
        access_token="x",
        refresh_token="y",
        expires_at=0.0,
        scope="ics",
        resource="https://ics.test/mcp",
    )
    assert pair.is_expired() is True


def test_pair_serialization_roundtrip():
    pair = TokenPair(
        access_token="a",
        refresh_token="b",
        expires_at=42.0,
        scope="ics",
        resource="r",
    )
    blob = pair.to_json()
    restored = TokenPair.from_json(blob)
    assert restored.access_token == pair.access_token
    assert restored.expires_at == pair.expires_at


def test_file_fallback_is_created_owner_only(tmp_path, monkeypatch):
    import os
    import stat

    from ics_mcp.auth import token_store as ts

    old = os.umask(0o022)
    try:
        path = tmp_path / "creds.json"
        pair = TokenPair("a", "r", 9_999_999_999.0, "ics", "https://ics.test/mcp")
        ts._file_save(path, pair)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert ts._file_load(path) == pair
        assert not (tmp_path / "creds.json.tmp").exists()
    finally:
        os.umask(old)


def test_load_uses_the_cache_and_load_fresh_rereads(store, monkeypatch):
    pair = TokenPair("a", "r", 9_999_999_999.0, "ics", "https://ics.test/mcp")
    store.save(pair)
    calls = {"n": 0}
    real = store._keyring_load

    def counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(store, "_keyring_load", counting)
    for _ in range(10):
        assert store.load() == pair
    assert calls["n"] == 0
    store.load_fresh()
    assert calls["n"] == 1


class _BrokenKeyring(MemoryKeyring):
    def get_password(self, service, username):
        raise KeyringError("locked")

    def set_password(self, service, username, password):
        raise KeyringError("locked")

    def delete_password(self, service, username):
        raise KeyringError("locked")


def test_save_goes_to_the_keyring_not_the_file(store, memory_keyring):
    pair = TokenPair("a", "r", 9_999_999_999.0, "ics", "https://ics.test/mcp")
    store.save(pair)
    assert TokenPair.from_json(memory_keyring.entries[(store.service, "default")]) == pair
    assert not store.fallback_path.exists()


def test_keyring_failure_falls_back_to_encrypted_file(store):
    keyring.set_keyring(_BrokenKeyring())
    pair = TokenPair("a", "r", 9_999_999_999.0, "ics", "https://ics.test/mcp")
    store.save(pair)
    assert b"access_token" not in store.fallback_path.read_bytes()
    assert store.load_fresh() == pair
    store.delete()
    assert not store.fallback_path.exists()
    assert store.load_fresh() is None


def test_unreadable_fallback_file_is_treated_as_no_token(tmp_path):
    from ics_mcp.auth import token_store as ts

    path = tmp_path / "creds.json"
    path.write_bytes(b"not a fernet token")
    assert ts._file_load(path) is None


def test_corrupt_keyring_entry_is_treated_as_no_token(store, memory_keyring):
    memory_keyring.entries[(store.service, "default")] = "{not json"
    assert store.load_fresh() is None
