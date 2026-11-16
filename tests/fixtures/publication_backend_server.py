"""Real ICS server in a disposable vault, with a real synthetic OAuth principal.

Executed only by publication_backend_smoke.py in the backend's own interpreter.
No route, storage, publication, permission or authentication dependency is mocked.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

backend, scratch = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(backend / "backend"))
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
os.environ.update(ICS_BASE_URL=base_url, ICS_MCP_RESOURCE_URI=f"{base_url}/mcp")
subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend / "backend", check=True
)

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Project, ProjectMember, User  # noqa: E402
from app.oauth.tokens import sign_access_jwt  # noqa: E402


async def main() -> None:
    import uvicorn

    engine.echo = False
    async with SessionLocal() as session:
        user = User(
            email="publication-smoke@example.com",
            display_name="Synthetic publisher",
            auth_method="google_sso",
            email_verified_at=datetime.now(UTC),
        )
        session.add(user)
        await session.flush()
        project = Project(
            slug="publication-smoke", name="Synthetic publication", created_by=user.id
        )
        session.add(project)
        await session.flush()
        session.add(
            ProjectMember(
                project_id=project.id, user_id=user.id, role="owner", accepted_at=datetime.now(UTC)
            )
        )
        await session.commit()
        token, _ = sign_access_jwt(
            settings=get_settings(),
            user=user,
            client_id_external="publication-smoke",
            scopes=["ics"],
            audience=f"{base_url}/mcp",
        )
    # The caller never logs this file, and its temporary directory is private.
    with open(
        scratch / "ready.json", "x", opener=lambda path, flags: os.open(path, flags, 0o600)
    ) as output:
        json.dump({"url": base_url, "token": token, "project_id": str(project.id)}, output)
    # Produce a real PDF for the document replacement endpoint, without adding
    # PDF dependencies to the MCP client package.
    from tests.pdf_factory import make_pdf

    (scratch / "report.pdf").write_bytes(make_pdf(["Publication receipt smoke"]))
    await uvicorn.Server(uvicorn.Config(create_app(), log_level="warning")).serve(
        sockets=[listener]
    )
    await engine.dispose()


asyncio.run(main())
