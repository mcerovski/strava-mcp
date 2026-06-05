"""Token storage (single DB row) + near-expiry auto-refresh (research R4).

The ``tokens`` table is the source of record once present; the ``.env`` seed is
used only to bootstrap before the first ``auth`` run. On each worker request the
access token is refreshed when within the margin of expiry, persisting the
(possibly rotated) refresh token.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from strava_mcp.config import STRAVA_OAUTH_TOKEN, Settings
from strava_mcp.db.repositories import now_iso

# Refresh when the access token expires within this many seconds.
REFRESH_MARGIN_SECONDS = 300


@dataclass(frozen=True)
class TokenSet:
    """A persisted OAuth token set."""

    access_token: str
    refresh_token: str
    expires_at: int
    scope: str

    def is_expired(self, *, now: float, margin: int = REFRESH_MARGIN_SECONDS) -> bool:
        return self.expires_at <= now + margin


def token_set_from_response(payload: dict[str, Any], *, scope: str) -> TokenSet:
    """Build a TokenSet from a Strava /oauth/token response body."""
    return TokenSet(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_at=int(payload["expires_at"]),
        scope=scope,
    )


class TokenStore:
    """Read/write the single ``tokens`` row, with DB-over-``.env`` precedence."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        now: Callable[[], float] = time.time,
        client: httpx.Client | None = None,
    ) -> None:
        self.conn = conn
        self.settings = settings
        self._now = now
        self._client = client

    # --- persistence -------------------------------------------------------
    def read(self) -> TokenSet | None:
        """Return the persisted token row, or None if not yet stored."""
        row = self.conn.execute(
            "SELECT access_token, refresh_token, expires_at, scope FROM tokens WHERE id = 1"
        ).fetchone()
        if row is None:
            return None
        return TokenSet(
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            expires_at=int(row["expires_at"]),
            scope=row["scope"],
        )

    def save(self, tokens: TokenSet) -> None:
        """Persist (replace) the single token row."""
        self.conn.execute(
            "INSERT OR REPLACE INTO tokens "
            "(id, access_token, refresh_token, expires_at, scope, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (
                tokens.access_token,
                tokens.refresh_token,
                tokens.expires_at,
                tokens.scope,
                now_iso(),
            ),
        )
        self.conn.commit()

    def _seed_from_env(self) -> TokenSet | None:
        s = self.settings
        if s.strava_access_token and s.strava_refresh_token:
            return TokenSet(
                access_token=s.strava_access_token,
                refresh_token=s.strava_refresh_token,
                expires_at=int(s.strava_token_expires_at or 0),
                scope=s.strava_token_scope or s.strava_scopes,
            )
        return None

    def current(self) -> TokenSet:
        """The active token set: DB row if present, else the ``.env`` seed.

        Raises if neither exists (the operator must run ``auth`` first).
        """
        tokens = self.read() or self._seed_from_env()
        if tokens is None:
            raise RuntimeError("No tokens available; run `uv run strava-mcp auth`.")
        return tokens

    # --- refresh -----------------------------------------------------------
    def refresh(self, tokens: TokenSet) -> TokenSet:
        """Exchange the refresh token for a fresh access token; persist + return."""
        client = self._client or httpx.Client(timeout=30.0)
        try:
            resp = client.post(
                STRAVA_OAUTH_TOKEN,
                data={
                    "client_id": self.settings.strava_client_id,
                    "client_secret": self.settings.strava_client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": tokens.refresh_token,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        finally:
            if self._client is None:
                client.close()
        # Scope is preserved across refresh (Strava does not echo it here).
        refreshed = token_set_from_response(payload, scope=tokens.scope)
        self.save(refreshed)
        return refreshed

    def access_token(self) -> str:
        """Return a valid access token, refreshing if within the expiry margin.

        This is the ``token_provider`` injected into the Strava HTTP client.
        """
        tokens = self.current()
        if tokens.is_expired(now=self._now()):
            tokens = self.refresh(tokens)
        return tokens.access_token
