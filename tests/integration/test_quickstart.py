"""T069 End-to-end walk of the quickstart.md scenarios against fixtures.

Drives the full worker lifecycle (BOOTSTRAP → BACKFILL → POLL) over one DB and
validates each agent-facing scenario through the real read tools — no live API.
This is the consolidated quickstart validation record.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from strava_mcp.config import Settings
from strava_mcp.db.repositories.activities import parse_epoch
from strava_mcp.mcp.tools.activities import (
    get_activity,
    get_activity_zones,
    get_comments,
    get_kudos,
    get_laps,
    list_activities,
)
from strava_mcp.mcp.tools.athlete import get_athlete
from strava_mcp.mcp.tools.gear import get_gear, list_gear
from strava_mcp.mcp.tools.routes import get_route, list_routes
from strava_mcp.mcp.tools.segments import (
    get_segment,
    list_segment_efforts,
    list_starred_segments,
)
from strava_mcp.mcp.tools.streams import get_activity_streams
from strava_mcp.mcp.tools.summaries import summarize_training
from strava_mcp.mcp.tools.sync import sync_status
from strava_mcp.sync.orchestrator import Orchestrator
from strava_mcp.sync.state import SyncState

from tests.conftest import FakeStravaClient
from tests.fixtures import load


def _settings() -> Settings:
    return Settings(strava_client_id="c", strava_client_secret="s", _env_file=None)


# One real activity (900003) drawn from the recorded fixtures.
_SUMMARY = {
    "id": 900003,
    "name": "Morning Ride",
    "sport_type": "Ride",
    "start_date": "2021-05-30T08:00:00Z",
    "distance": 32000.0,
    "moving_time": 3600,
    "total_elevation_gain": 350.0,
}


def _handler(path: str, params: dict[str, Any]) -> Any:
    if path == "/athlete":
        return load("athlete")
    if path == "/athlete/zones":
        return load("athlete_zones")
    if path.endswith("/stats"):
        return load("athlete_stats")
    if path == "/gear/b1234":
        return load("gear")
    if path == "/gear/g5678":
        return {"id": "g5678", "name": "Trail Shoes", "type": "shoe"}
    if path.endswith("/routes"):
        return [{"id": 770099, "id_str": "770099"}]
    if path == "/routes/770099":
        return load("route")
    if path == "/segments/starred":
        return [{"id": 550010}]
    if path == "/segments/550010":
        return load("segment")
    if path == "/athlete/activities":
        if params.get("before") is None and params.get("after") is None:
            return [_SUMMARY]
        return []
    suffix = path.split("/activities/900003")[-1]
    if suffix == "":
        return load("activity_detail")
    if suffix == "/streams":
        return load("streams")
    if suffix in ("/laps", "/comments", "/kudos", "/zones"):
        return load(suffix.strip("/"))
    raise AssertionError(path)


def test_quickstart_end_to_end(conn: sqlite3.Connection, db_path: Path) -> None:
    orch = Orchestrator(conn, FakeStravaClient(_handler), _settings())
    orch.bootstrap()
    orch.backfill()

    # Scenario 2 — athlete read.
    athlete = get_athlete(db_path)
    assert athlete["profile"]["id"] == 12345

    # Scenario 3 — activity list/filter + status.
    acts = list_activities(db_path, sport_type="Ride")
    assert [a["id"] for a in acts] == [900003]
    status = sync_status(db_path)
    assert status["backfill_complete"] is True
    assert status["counts"]["enriched"] == 1

    # Scenario 4 — enrichment facets.
    assert get_activity(db_path, 900003)["id"] == 900003
    assert len(get_laps(db_path, 900003)) == 2
    assert len(get_comments(db_path, 900003)) == 2
    assert len(get_kudos(db_path, 900003)) == 3
    assert len(get_activity_zones(db_path, 900003)) == 2

    # Scenario 5 — streams + fully synced.
    streams = get_activity_streams(db_path, 900003, keys=["heartrate", "watts"])
    assert set(streams["streams"]) == {"heartrate", "watts"}
    assert SyncState(conn).is_fully_synced() is True
    assert sync_status(db_path)["fully_synced"] is True

    # Scenario 6 — gear / routes / segments.
    assert {g["id"] for g in list_gear(db_path)} == {"b1234", "g5678"}
    assert get_gear(db_path, "b1234")["brand_name"] == "Trek"
    assert {r["id_str"] for r in list_routes(db_path)} == {"770099"}
    assert "map" in get_route(db_path, "770099")
    assert [s["id"] for s in list_starred_segments(db_path)] == [550010]
    assert get_segment(db_path, 550010)["effort_count"] == 120  # starred → full detail
    assert get_segment(db_path, 660001)["id"] == 660001  # encountered → summary
    assert len(list_segment_efforts(db_path, 660001)) == 1

    # Scenario 7 — steady-state poll (insert-only, no mutation of existing rows).
    SyncState(conn).set_newest_synced(parse_epoch("2021-05-30T08:00:00Z"))
    inserted = orch.poll()
    assert inserted == []  # the only activity is already stored → no re-insert
    assert sync_status(db_path)["counts"]["enriched"] == 1

    # Scenario 8 — training summary.
    weekly = summarize_training(db_path, period="weekly")
    assert weekly and weekly[0]["count"] == 1
    assert weekly[0]["distance"] == 32000.0


def test_quickstart_pending_activity_is_invisible(conn: sqlite3.Connection, db_path: Path) -> None:
    # An activity the frontier hasn't enriched is never partially exposed.
    from strava_mcp.db.repositories.activities import ActivitiesRepository

    ActivitiesRepository(conn).insert_summary(
        {"id": 111, "start_date": "2019-01-01T00:00:00Z", "sport_type": "Run"}
    )
    assert get_activity(db_path, 111) == {"status": "not_yet_synced", "id": 111}
    assert get_activity_streams(db_path, 111) == {"status": "not_yet_synced", "id": 111}
    assert list_activities(db_path) == []  # invisible until fully enriched
