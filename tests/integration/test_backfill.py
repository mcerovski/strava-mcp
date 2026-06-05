"""T027 [US3] Backfill paging newest→oldest, checkpoint, resume, cooldown.

Backfill enriches each activity as a unit (US4), so the handler also serves the
enrichment endpoints; the assertions here cover the US3 paging mechanics.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from strava_mcp.client.http import RateLimitExceeded
from strava_mcp.config import Settings
from strava_mcp.db.repositories.activities import parse_epoch
from strava_mcp.sync.orchestrator import Orchestrator

from tests.conftest import FakeClock, FakeStravaClient, build_handler

# Six activities, newest first, one day apart.
_ACTIVITIES: list[dict[str, Any]] = [
    {
        "id": 1000 + i,
        "name": f"Activity {i}",
        "sport_type": "Ride" if i % 2 == 0 else "Run",
        "start_date": f"2021-05-{20 - i:02d}T08:00:00Z",
        "distance": 10000.0 + i,
        "moving_time": 3000,
        "elapsed_time": 3100,
        "total_elevation_gain": 100.0,
        "kudos_count": i,
        "comment_count": 0,
        "athlete": {"id": 12345},
    }
    for i in range(6)
]


def _settings() -> Settings:
    return Settings(strava_client_id="c", strava_client_secret="s", _env_file=None)


def test_backfill_pages_newest_to_oldest_and_completes(conn: sqlite3.Connection) -> None:
    client = FakeStravaClient(build_handler(_ACTIVITIES))
    Orchestrator(conn, client, _settings(), per_page=2).backfill()

    ids = [
        r["id"] for r in conn.execute("SELECT id FROM activities ORDER BY start_date_epoch DESC")
    ]
    assert ids == [1000, 1001, 1002, 1003, 1004, 1005]
    # Every activity is enriched (visible) and carries a streams row.
    assert (
        conn.execute("SELECT COUNT(*) FROM activities WHERE enriched_at IS NOT NULL").fetchone()[0]
        == 6
    )
    assert conn.execute("SELECT COUNT(*) FROM activity_streams").fetchone()[0] == 6

    state = conn.execute(
        "SELECT backfill_complete, backfill_frontier_epoch FROM sync_state"
    ).fetchone()
    assert state["backfill_complete"] == 1
    assert state["backfill_frontier_epoch"] == parse_epoch("2021-05-15T08:00:00Z")


def test_restart_resumes_with_zero_refetch(conn: sqlite3.Connection) -> None:
    summary_pages: list[list[int]] = []

    def tracking(inner: Any) -> Any:
        def handler(path: str, params: dict[str, Any]) -> Any:
            result = inner(path, params)
            if path == "/athlete/activities":
                summary_pages.append([a["id"] for a in result])
            return result

        return handler

    base = build_handler(_ACTIVITIES, per_page=2)
    Orchestrator(conn, FakeStravaClient(tracking(base)), _settings(), per_page=2).backfill(
        max_pages=1
    )
    assert {r["id"] for r in conn.execute("SELECT id FROM activities")} == {1000, 1001}

    summary_pages.clear()
    Orchestrator(conn, FakeStravaClient(tracking(base)), _settings(), per_page=2).backfill()

    # The resumed run never re-fetches the two already-stored activities.
    refetched = {aid for page in summary_pages for aid in page}
    assert 1000 not in refetched and 1001 not in refetched
    assert {r["id"] for r in conn.execute("SELECT id FROM activities")} == {
        1000,
        1001,
        1002,
        1003,
        1004,
        1005,
    }


def test_budget_exhaustion_triggers_cooldown_then_resumes(conn: sqlite3.Connection) -> None:
    clock = FakeClock(parse_epoch("2021-06-01T12:07:00Z"))
    slept: list[str] = []
    base = build_handler(_ACTIVITIES, per_page=10)
    raised = {"done": False}

    def handler(path: str, params: dict[str, Any]) -> Any:
        if path == "/athlete/activities" and not raised["done"]:
            raised["done"] = True
            raise RateLimitExceeded(429, "Too Many Requests")
        return base(path, params)

    def fake_sleep(seconds: float) -> None:
        clock.advance(seconds)
        slept.append("slept")

    orch = Orchestrator(
        conn,
        FakeStravaClient(handler),
        _settings(),
        clock=clock.time,
        sleep=fake_sleep,
        per_page=10,
    )
    orch.backfill()

    assert slept, "expected a cooldown sleep"
    assert conn.execute("SELECT backfill_complete FROM sync_state").fetchone()[0] == 1
    assert conn.execute("SELECT cooldown_until FROM sync_state").fetchone()[0] is None
    assert {r["id"] for r in conn.execute("SELECT id FROM activities")} == {
        1000,
        1001,
        1002,
        1003,
        1004,
        1005,
    }
