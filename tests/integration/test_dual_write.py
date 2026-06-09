"""T067 Dual-write invariant: every normalized write has a matching raw_responses row.

Directly-fetched resources each carry their own raw row. Derived rows
(segment_efforts, encountered segments) are projections of an already-recorded
``activity_detail`` payload (ADR 0001/0002) and are checked via that backing row.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from strava_mcp.config import Settings
from strava_mcp.sync.orchestrator import Orchestrator

from tests.conftest import FakeStravaClient
from tests.fixtures import load


def _settings() -> Settings:
    return Settings(strava_client_id="c", strava_client_secret="s", _env_file=None)


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
        return {"id": "g5678", "name": "Shoes"}
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
            return [{"id": 900003, "start_date": "2021-05-30T08:00:00Z", "sport_type": "Ride"}]
        return []
    suffix = path.split("/activities/900003")[-1]
    if suffix == "":
        return load("activity_detail")
    if suffix == "/streams":
        return load("streams")
    if suffix in ("/laps", "/zones"):
        return load(suffix.strip("/"))
    raise AssertionError(path)


def _raw_for(conn: sqlite3.Connection, resource_type: str, resource_id: Any) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM raw_responses WHERE resource_type = ? AND resource_id = ?",
        (resource_type, str(resource_id)),
    ).fetchone()[0]


def test_every_normalized_row_has_a_backing_raw_row(conn: sqlite3.Connection) -> None:
    orch = Orchestrator(conn, FakeStravaClient(_handler), _settings())
    orch.bootstrap()
    orch.backfill()

    # Directly-fetched single/collection resources.
    for (athlete_id,) in conn.execute("SELECT id FROM athlete"):
        assert _raw_for(conn, "athlete", athlete_id) >= 1
    for (gear_id,) in conn.execute("SELECT id FROM gear"):
        assert _raw_for(conn, "gear", gear_id) >= 1
    for (route_id,) in conn.execute("SELECT id FROM routes"):
        assert _raw_for(conn, "route", route_id) >= 1
    for (segment_id,) in conn.execute("SELECT id FROM segments WHERE starred = 1"):
        assert _raw_for(conn, "segment", segment_id) >= 1

    # Per-activity enrichment: detail + each facet + streams all recorded raw.
    for (activity_id,) in conn.execute("SELECT id FROM activities WHERE enriched_at IS NOT NULL"):
        assert _raw_for(conn, "activity_detail", activity_id) >= 1
        assert _raw_for(conn, "streams", activity_id) >= 1
        for facet in ("laps", "zones"):
            assert _raw_for(conn, facet, activity_id) >= 1

    # Derived rows are backed by the activity_detail raw payload.
    for (activity_id,) in conn.execute("SELECT DISTINCT activity_id FROM segment_efforts"):
        assert _raw_for(conn, "activity_detail", activity_id) >= 1


def test_no_normalized_table_written_without_any_raw(conn: sqlite3.Connection) -> None:
    Orchestrator(conn, FakeStravaClient(_handler), _settings()).run_once()
    normalized = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    raw = conn.execute("SELECT COUNT(*) FROM raw_responses").fetchone()[0]
    assert normalized > 0 and raw >= normalized
