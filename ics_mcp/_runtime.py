"""Runtime singleton bound by the `server.build_mcp()` lifespan. Tool modules
dereference `runtime.ics` at call time, never at import time, because the
lifespan has not run yet then."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ics_mcp.ics_client import ICSClient


@dataclass(slots=True)
class Runtime:
    ics: ICSClient | None = None

    def require_ics(self) -> ICSClient:
        if self.ics is None:
            raise RuntimeError("ICS client not initialized (lifespan not yet started)")
        return self.ics


runtime = Runtime()
