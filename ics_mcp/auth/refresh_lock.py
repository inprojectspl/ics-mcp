"""A lock file shared by every ics-mcp process of one profile, held while one
of them spends the refresh token. Without it two processes (say Claude
Desktop and Claude Code) refresh with the same token at once: the server
rotates it for the first and treats the second as a replay."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from ics_mcp.logging import get_logger

_log = get_logger(__name__)

#: A refresh is one HTTP round trip; past this a holder is taken to be stuck
#: and the waiter goes ahead, which is no worse than having no lock.
_WAIT_SECONDS = 30.0
_POLL_SECONDS = 0.05

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@asynccontextmanager
async def refresh_lock(path: Path, *, wait: float = _WAIT_SECONDS) -> AsyncIterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        deadline = time.monotonic() + wait
        while not (locked := _try_lock(fd)):
            if time.monotonic() >= deadline:
                _log.warning("refresh lock still held, going ahead", path=str(path))
                break
            await asyncio.sleep(_POLL_SECONDS)
        yield
    finally:
        if locked:
            _unlock(fd)
        os.close(fd)
