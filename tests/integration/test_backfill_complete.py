"""T071 [US3] Backfill termination at first-ever activity + empty-account case.

Closes spec Edge Case "Empty account / first-ever activity".
"""

from __future__ import annotations

import sqlite3
from typing import Any

from strava_mcp.config import Settings
from strava_mcp.sync.orchestrator import Orchestrator

from tests.conftest import FakeStravaClient, build_handler


def _settings() -> Settings:
    return Settings(strava_client_id="c", strava_client_secret="s", _env_file=None)


def test_empty_account_marks_backfill_complete(conn: sqlite3.Connection) -> None:
    orch = Orchestrator(conn, FakeStravaClient(build_handler([])), _settings())
    orch.backfill()

    assert (
        conn.execute("SELECT backfill_complete FROM sync_state").fetchone()["backfill_complete"]
        == 1
    )
    assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0


def test_single_activity_terminates_after_first_ever(conn: sqlite3.Connection) -> None:
    only = {
        "id": 42,
        "name": "First Ever",
        "sport_type": "Ride",
        "start_date": "2014-01-01T08:00:00Z",
        "distance": 12000.0,
    }
    summary_calls: list[int] = []
    base = build_handler([only], per_page=5)

    def handler(path: str, params: dict[str, Any]) -> Any:
        if path == "/athlete/activities":
            summary_calls.append(1)
        return base(path, params)

    Orchestrator(conn, FakeStravaClient(handler), _settings(), per_page=5).backfill()

    assert conn.execute("SELECT backfill_complete FROM sync_state").fetchone()[0] == 1
    assert {r["id"] for r in conn.execute("SELECT id FROM activities")} == {42}
    # Paged once with data, once more to confirm no older activity, then stopped.
    assert len(summary_calls) == 2
