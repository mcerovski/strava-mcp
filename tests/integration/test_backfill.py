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


def test_enrich_page_skips_already_enriched_on_resume(conn: sqlite3.Connection) -> None:
    """A re-fetched page does not re-enrich activities already stored (zero re-fetch)."""
    page = _ACTIVITIES[:3]
    first = Orchestrator(conn, FakeStravaClient(build_handler(page)), _settings())
    first.activities_syncer.store_summaries(page)
    first._enrich_page(page)
    assert (
        conn.execute("SELECT COUNT(*) FROM activities WHERE enriched_at IS NOT NULL").fetchone()[0]
        == 3
    )

    # Second pass over the same page: any enrichment fetch would be a re-fetch.
    def strict(path: str, params: dict[str, Any]) -> Any:
        if path.startswith("/activities/"):
            raise AssertionError(f"re-fetched already-enriched activity: {path}")
        raise AssertionError(path)

    second = Orchestrator(conn, FakeStravaClient(strict), _settings())
    second.activities_syncer.store_summaries(page)  # INSERT OR IGNORE → no-op
    second._enrich_page(page)  # must skip all three without any enrichment call
    assert (
        conn.execute("SELECT COUNT(*) FROM activities WHERE enriched_at IS NOT NULL").fetchone()[0]
        == 3
    )


def test_bootstrap_athlete_cools_down_on_rate_limit(conn: sqlite3.Connection) -> None:
    """A 429 on the first athlete fetch cools down and retries — never crashes."""
    clock = FakeClock(parse_epoch("2026-06-05T07:52:00Z"))
    slept: list[int] = []
    raised = {"n": 0}

    def handler(path: str, params: dict[str, Any]) -> Any:
        if path == "/athlete":
            if raised["n"] == 0:
                raised["n"] += 1
                raise RateLimitExceeded(429, "Rate Limit Exceeded")
            return {"id": 12345, "username": "a", "bikes": [], "shoes": []}
        if path == "/athlete/zones":
            return {}
        if path.endswith("/stats"):
            return {}
        if path.endswith("/routes"):
            return []
        if path == "/segments/starred":
            return []
        raise AssertionError(path)

    def fake_sleep(seconds: float) -> None:
        clock.advance(seconds)
        slept.append(1)

    orch = Orchestrator(
        conn, FakeStravaClient(handler), _settings(), clock=clock.time, sleep=fake_sleep
    )
    orch.bootstrap()  # must not raise

    assert slept, "expected a cooldown before retrying"
    assert conn.execute("SELECT id FROM athlete").fetchone()["id"] == 12345


def test_cooldown_uses_daily_window_for_tierless_429(conn: sqlite3.Connection) -> None:
    """A raw 429 with the daily budget spent cools to midnight UTC, not :15."""
    import json

    from strava_mcp.client.ratelimit import RateLimitBudget

    clock = FakeClock(parse_epoch("2026-06-05T12:07:00Z"))
    budget = RateLimitBudget(clock=clock.time)
    # Daily usage at the limit; 15-min well under.
    budget.record({"X-ReadRateLimit-Usage": "10,1000", "X-ReadRateLimit-Limit": "100,1000"})

    orch = Orchestrator(
        conn, FakeStravaClient(lambda p, q: None), _settings(), budget=budget, clock=clock.time
    )
    orch.state.ensure()
    orch.stop_event.set()  # skip the real wait; we only assert the chosen window
    orch._cooldown(RateLimitExceeded(429, "Rate Limit Exceeded"))

    entries = json.loads(orch.state.snapshot()["run_log_json"])
    cooldown = [e for e in entries if e.get("phase") == "COOLDOWN"][-1]
    assert cooldown["until"] == "2026-06-06T00:00:00Z"  # daily reset, not 12:15
