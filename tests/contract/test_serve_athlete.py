"""T017 [US2] serve scope-check-or-exit + get_athlete pure-read."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from strava_mcp.auth.tokens import TokenSet, TokenStore
from strava_mcp.config import Settings
from strava_mcp.mcp import server
from strava_mcp.mcp.tools.athlete import get_athlete
from strava_mcp.sync.orchestrator import Orchestrator

from tests.conftest import FakeStravaClient
from tests.fixtures import load


def _settings(db_path: Path, **overrides: object) -> Settings:
    base = dict(
        strava_client_id="c",
        strava_client_secret="s",
        strava_db_path=str(db_path),
        _env_file=None,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _handler(path: str, params: dict[str, object]) -> object:
    if path == "/athlete":
        return load("athlete")
    if path == "/athlete/zones":
        return load("athlete_zones")
    if path.endswith("/stats"):
        return load("athlete_stats")
    raise AssertionError(path)


def test_serve_refuses_under_scoped_token(conn: sqlite3.Connection, db_path: Path) -> None:
    settings = _settings(db_path)
    TokenStore(conn, settings).save(TokenSet("a", "r", 9_999_999_999, "read"))
    conn.commit()
    assert server.check_scopes(settings) == [
        "read_all",
        "profile:read_all",
        "activity:read",
        "activity:read_all",
    ]


def test_serve_accepts_full_scope_token(conn: sqlite3.Connection, db_path: Path) -> None:
    settings = _settings(db_path)
    TokenStore(conn, settings).save(
        TokenSet(
            "a",
            "r",
            9_999_999_999,
            ",".join(
                ["read", "read_all", "profile:read_all", "activity:read", "activity:read_all"]
            ),
        )
    )
    conn.commit()
    assert server.check_scopes(settings) == []


def test_serve_refuses_when_no_token(db_path: Path) -> None:
    settings = _settings(db_path)
    # No tokens persisted, no env seed → all scopes reported missing.
    assert len(server.check_scopes(settings)) == 5


def test_get_athlete_not_yet_synced_before_bootstrap(db_path: Path) -> None:
    from strava_mcp.db import engine

    engine.connect(db_path).close()  # create empty schema
    assert get_athlete(db_path) == {"status": "not_yet_synced"}


def test_get_athlete_returns_profile_after_bootstrap(
    conn: sqlite3.Connection, db_path: Path
) -> None:
    orch = Orchestrator(conn, FakeStravaClient(_handler), _settings(db_path))
    orch.bootstrap()
    result = get_athlete(db_path)
    assert result["profile"]["id"] == 12345
    assert result["zones"]["heart_rate"]["zones"]
    assert result["stats"]["all_ride_totals"]["count"] == 500
