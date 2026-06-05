"""T059 [US7] POLL lookback + dedupe-by-id + insert-only + back-dated capture."""

from __future__ import annotations

import sqlite3
from typing import Any

from strava_mcp.config import Settings
from strava_mcp.db.repositories.activities import parse_epoch
from strava_mcp.sync.orchestrator import Orchestrator
from strava_mcp.sync.state import SyncState

from tests.conftest import FakeStravaClient, build_handler


def _settings() -> Settings:
    return Settings(strava_client_id="c", strava_client_secret="s", _env_file=None)


def _act(aid: int, date: str, sport: str = "Ride") -> dict[str, Any]:
    return {
        "id": aid,
        "name": f"A{aid}",
        "sport_type": sport,
        "start_date": date,
        "distance": 1000.0,
    }


def test_poll_inserts_new_and_backdated_only(conn: sqlite3.Connection) -> None:
    # Pre-existing fully-synced state: one activity already stored + enriched.
    existing = _act(1, "2021-06-01T08:00:00Z")
    dataset = [existing]
    Orchestrator(conn, FakeStravaClient(build_handler(dataset)), _settings()).backfill()

    state = SyncState(conn)
    state.set_newest_synced(parse_epoch("2021-06-01T08:00:00Z"))

    # New activity (after newest) and a back-dated one within the 14-day window.
    new_act = _act(2, "2021-06-03T08:00:00Z")
    backdated = _act(3, "2021-05-25T08:00:00Z")  # within 14 days of newest
    dataset.extend([new_act, backdated])

    inserted = Orchestrator(conn, FakeStravaClient(build_handler(dataset)), _settings()).poll()

    assert set(inserted) == {2, 3}
    ids = {r["id"] for r in conn.execute("SELECT id FROM activities WHERE enriched_at IS NOT NULL")}
    assert ids == {1, 2, 3}
    # newest_synced advanced to the new activity.
    assert conn.execute("SELECT newest_synced_epoch FROM sync_state").fetchone()[0] == parse_epoch(
        "2021-06-03T08:00:00Z"
    )


def test_poll_dedupes_and_never_mutates(conn: sqlite3.Connection) -> None:
    existing = _act(1, "2021-06-01T08:00:00Z")
    Orchestrator(conn, FakeStravaClient(build_handler([existing])), _settings()).backfill()
    SyncState(conn).set_newest_synced(parse_epoch("2021-06-01T08:00:00Z"))

    before_detail = conn.execute(
        "SELECT detail_json, enriched_at FROM activities WHERE id=1"
    ).fetchone()
    before_raw_count = conn.execute("SELECT COUNT(*) FROM raw_responses").fetchone()[0]

    # Poll returns the same activity (id 1 already stored) → must be skipped.
    inserted = Orchestrator(conn, FakeStravaClient(build_handler([existing])), _settings()).poll()

    assert inserted == []
    after_detail = conn.execute(
        "SELECT detail_json, enriched_at FROM activities WHERE id=1"
    ).fetchone()
    assert after_detail["detail_json"] == before_detail["detail_json"]
    assert after_detail["enriched_at"] == before_detail["enriched_at"]
    # No new raw rows written for the deduped activity (insert-only, no re-fetch enrichment).
    assert conn.execute("SELECT COUNT(*) FROM raw_responses").fetchone()[0] == before_raw_count


def test_poll_phase_recorded_in_run_log(conn: sqlite3.Connection) -> None:
    Orchestrator(conn, FakeStravaClient(build_handler([])), _settings()).poll()
    phase = conn.execute("SELECT phase FROM sync_state WHERE id=1").fetchone()[0]
    assert phase == "POLL"
