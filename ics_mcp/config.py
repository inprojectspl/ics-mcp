"""Pydantic settings: environment-driven configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Canonical set of confirm modes; every other module imports it from here so
# the names cannot drift. It is defined in config.py because this is the
# lowest module in the import graph, so anything can import it without a cycle.
ConfirmMode = Literal["interactive", "yolo", "dry_run"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ICS_", case_sensitive=False)

    # ICS endpoint
    base_url: str = "http://ics.localhost"
    mcp_resource_uri: str = "http://ics.localhost/mcp"

    # OAuth client (must be pre-registered in ICS). PKCE-only, public client.
    mcp_oauth_client_id: str = "ics-mcp-stdio"

    # Transport
    # Public issuer URL when ICS_BASE_URL is an internal address (HTTP deploys).
    mcp_oauth_issuer: str = ""

    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_host: str = "127.0.0.1"
    mcp_http_port: int = 8765
    mcp_stateless: bool = False
    mcp_extra_origins: str = ""

    # Token storage
    mcp_keyring_service: str = "ics-mcp"
    mcp_token_fallback_path: str = ""

    # Behavior
    mcp_default_confirm: ConfirmMode = "interactive"
    # Whether the model may switch its own session to `yolo`. Off by default:
    # a prompt-injected instruction must not be able to disable confirmations.
    mcp_allow_yolo: bool = False
    mcp_log_level: str = "INFO"
    # Upload caps, checked before anything is read into memory. The byte cap
    # matches the ICS default for one asset (max_asset_bytes).
    mcp_max_upload_bytes: int = 100 * 1024 * 1024
    mcp_max_upload_files: int = 500

    @field_validator("mcp_default_confirm", mode="before")
    @classmethod
    def _legacy_ask_alias(cls, v: object) -> object:
        # Legacy name of the default mode: accept `ICS_MCP_DEFAULT_CONFIRM=ask`
        # and map it.
        return "interactive" if v == "ask" else v

    # Performance
    mcp_response_max_chars: int = 8000
    mcp_http_timeout_read: int = 30
    mcp_http_timeout_write: int = 300

    @property
    def token_fallback_path_resolved(self) -> Path:
        if self.mcp_token_fallback_path:
            return Path(self.mcp_token_fallback_path)
        return Path(user_data_dir("ics-mcp")) / "credentials.json"

    @property
    def issuer(self) -> str:
        """Public identity of the ICS authorization server (the JWT `iss`).
        Differs from base_url when the MCP server reaches ICS over an
        internal address, e.g. http://backend:8000 inside compose."""
        return (self.mcp_oauth_issuer or self.base_url).rstrip("/")

    @property
    def authorize_url(self) -> str:
        return f"{self.issuer}/api/auth/oauth/authorize"

    @property
    def token_url(self) -> str:
        return f"{self.issuer}/api/auth/oauth/token"

    @property
    def jwks_url(self) -> str:
        # Fetched server-to-server, so it follows base_url, not the issuer.
        return f"{self.base_url.rstrip('/')}/api/auth/oauth/jwks.json"

    @property
    def extra_origins_list(self) -> list[str]:
        return [o.strip() for o in self.mcp_extra_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
