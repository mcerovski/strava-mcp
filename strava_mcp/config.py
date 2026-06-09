"""Typed configuration loaded from environment / ``.env`` (research R10).

Defaults mirror ``.env.example``. Client credentials are required to run ``auth``;
everything else has a sensible default for a single-user loopback deployment.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Read scopes the mirror needs. Private/Only-You data and zones require the
# ``*_all`` scopes (research R6). The granted scope is checked at auth and serve.
REQUIRED_SCOPES: tuple[str, ...] = (
    "read",
    "read_all",
    "profile:read_all",
    "activity:read",
    "activity:read_all",
)

STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_OAUTH_AUTHORIZE = "https://www.strava.com/oauth/authorize"
STRAVA_OAUTH_TOKEN = "https://www.strava.com/oauth/token"


class Settings(BaseSettings):
    """Process configuration; values come from env or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Strava app credentials ---
    strava_client_id: str = ""
    strava_client_secret: str = ""

    # --- OAuth flow ---
    strava_scopes: str = ",".join(REQUIRED_SCOPES)
    oauth_redirect_host: str = "127.0.0.1"
    oauth_redirect_port: int = 8721

    # --- Local database ---
    strava_db_path: str = "./.database/strava.db"

    # --- MCP HTTP server ---
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8720

    # --- Dashboard HTTP server (read-only UI; loopback only) ---
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8722

    # --- Sync tuning ---
    sync_max_requests: int = 900

    @property
    def scopes_list(self) -> list[str]:
        return [s.strip() for s in self.strava_scopes.split(",") if s.strip()]

    @property
    def redirect_uri(self) -> str:
        return f"http://{self.oauth_redirect_host}:{self.oauth_redirect_port}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
