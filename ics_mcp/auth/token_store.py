"""Persistent storage for the OAuth token pair: the OS keyring, or a `0600`
file when the platform has no keyring service.

The file is Fernet-encrypted with a key derived from the hostname, the UID and
a fixed pepper, which anything running as the same user can reproduce: that is
obfuscation against casual reading; the real protection is the `0600` mode.
"""

from __future__ import annotations

import base64
import json
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ics_mcp.logging import get_logger

_log = get_logger(__name__)


@dataclass(slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds
    scope: str
    resource: str

    def is_expired(self, leeway: int = 30) -> bool:
        return datetime.now(UTC).timestamp() + leeway >= self.expires_at

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_at": self.expires_at,
                "scope": self.scope,
                "resource": self.resource,
            }
        )

    @classmethod
    def from_json(cls, s: str) -> TokenPair:
        d = json.loads(s)
        return cls(
            access_token=d["access_token"],
            refresh_token=d["refresh_token"],
            expires_at=float(d["expires_at"]),
            scope=d.get("scope", "ics"),
            resource=d["resource"],
        )


@lru_cache(maxsize=1)
def _derive_file_key() -> bytes:
    pepper = b"ics-mcp::v1::fallback-token-store"
    salt = (socket.gethostname() + str(os.getuid() if hasattr(os, "getuid") else 0)).encode()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    return base64.urlsafe_b64encode(kdf.derive(pepper))


def _file_save(path: Path, pair: TokenPair) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = _derive_file_key()
    cipher = Fernet(key)
    ct = cipher.encrypt(pair.to_json().encode("utf-8"))
    # Create the temp file with 0600 from the start (no window with the
    # umask default), then swap it in atomically.
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, ct)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _file_load(path: Path) -> TokenPair | None:
    try:
        ct = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        cipher = Fernet(_derive_file_key())
        return TokenPair.from_json(cipher.decrypt(ct).decode("utf-8"))
    except Exception as e:
        _log.debug("token file unreadable", error=type(e).__name__)
        return None


class TokenStore:
    """Keyring first, then the `0600` file. Keyring failures are logged and
    skipped, not fatal: Linux servers without libsecret would be unusable."""

    def __init__(self, service: str, fallback_path: Path) -> None:
        self.service = service
        self.fallback_path = fallback_path
        self._account = "default"
        # In-process copy of the last pair read or written. Several ics-mcp
        # processes can share one keyring entry, so callers that are about
        # to refresh must use `load_fresh()`, never this copy.
        self._cached: TokenPair | None = None

    @property
    def lock_path(self) -> Path:
        """Lock file of this profile, for `refresh_lock`."""
        return self.fallback_path.with_name(self.fallback_path.name + ".lock")

    # ----------------------- keyring -----------------------
    def _keyring_save(self, pair: TokenPair) -> bool:
        try:
            import keyring

            keyring.set_password(self.service, self._account, pair.to_json())
            return True
        except Exception as e:
            _log.debug("keyring save failed", error=type(e).__name__)
            return False

    def _keyring_load(self) -> TokenPair | None:
        try:
            import keyring

            blob = keyring.get_password(self.service, self._account)
            if not blob:
                return None
            return TokenPair.from_json(blob)
        except Exception as e:
            _log.debug("keyring load failed", error=type(e).__name__)
            return None

    def _keyring_delete(self) -> bool:
        try:
            import keyring

            keyring.delete_password(self.service, self._account)
            return True
        except Exception as e:
            _log.debug("keyring delete failed", error=type(e).__name__)
            return False

    # ----------------------- public API -----------------------
    def save(self, pair: TokenPair) -> None:
        self._cached = pair
        if self._keyring_save(pair):
            return
        _file_save(self.fallback_path, pair)

    def load(self) -> TokenPair | None:
        """Cheap read for the hot path: the cached pair when there is one."""
        if self._cached is not None:
            return self._cached
        return self.load_fresh()

    def load_fresh(self) -> TokenPair | None:
        """Read from the keyring or file, bypassing the cache."""
        self._cached = self._keyring_load() or _file_load(self.fallback_path)
        return self._cached

    def delete(self) -> None:
        self._cached = None
        self._keyring_delete()
        if self.fallback_path.exists():
            try:
                self.fallback_path.unlink()
            except OSError:
                pass
