"""T047 [US6] BOOTSTRAP gear/routes/starred dual-write + starred-not-downgraded."""

from __future__ import annotations

import sqlite3
from typing import Any

from strava_mcp.config import Settings
from strava_mcp.db.repositories.activities import ActivitiesRepository
from strava_mcp.sync.orchestrator import Orchestrator
from strava_mcp.sync.resources.activities import ActivitiesSyncer

from tests.conftest import FakeStravaClient
from tests.fixtures import load


def _settings() -> Settings:
    return Settings(strava_client_id="c", strava_client_secret="s", _env_file=None)


def _bootstrap_handler(path: str, params: dict[str, Any]) -> Any:
    if path == "/athlete":
        return load("athlete")
    if path == "/athlete/zones":
        return load("athlete_zones")
    if path.endswith("/stats"):
        return load("athlete_stats")
    if path == "/gear/b1234":
        return load("gear")
    if path == "/gear/g5678":
        return {"id": "g5678", "name": "Trail Shoes", "type": "shoe", "distance": 400000.0}
    if path == "/athletes/12345/routes":
        return [{"id": 770099, "id_str": "770099", "name": "Hilly Loop"}]
    if path == "/routes/770099":
        return load("route")
    if path == "/segments/starred":
        return [{"id": 550010, "name": "Powell Butte Sprint"}]
    if path == "/segments/550010":
        return load("segment")
    raise AssertionError(path)


def test_bootstrap_mirrors_gear_routes_starred(conn: sqlite3.Connection) -> None:
    orch = Orchestrator(conn, FakeStravaClient(_bootstrap_handler), _settings())
    orch.bootstrap()

    assert conn.execute("SELECT COUNT(*) FROM gear").fetchone()[0] == 2
    assert conn.execute("SELECT type FROM gear WHERE id='b1234'").fetchone()[0] == "bike"
    assert conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0] == 1
    starred = conn.execute("SELECT id, starred FROM segments WHERE starred=1").fetchall()
    assert [(r["id"], r["starred"]) for r in starred] == [(550010, 1)]

    # Dual-write: raw rows exist for gear/route/segment.
    raw_types = {
        r["resource_type"] for r in conn.execute("SELECT resource_type FROM raw_responses")
    }
    assert {"gear", "route", "segment"} <= raw_types


def test_starred_not_downgraded_by_encountered(conn: sqlite3.Connection) -> None:
    # First, enrichment records segment 660001 as an encountered summary.
    repo = ActivitiesRepository(conn)
    repo.insert_summary({"id": 900003, "start_date": "2021-05-30T08:00:00Z"})

    def enrich_handler(path: str, params: dict[str, Any]) -> Any:
        suffix = path.split("/activities/900003")[-1]
        if suffix == "":
            return load("activity_detail")  # embeds segment 660001 (encountered)
        if suffix == "/streams":
            return load("streams")
        return []

    ActivitiesSyncer(FakeStravaClient(enrich_handler), repo).enrich(900003)
    enc = conn.execute("SELECT starred FROM segments WHERE id=660001").fetchone()
    assert enc["starred"] == 0  # encountered

    # Now a starred fetch for the same segment upgrades it.
    def starred_handler(path: str, params: dict[str, Any]) -> Any:
        if path == "/segments/starred":
            return [{"id": 660001, "name": "Tabor Climb"}]
        if path == "/segments/660001":
            return {"id": 660001, "name": "Tabor Climb", "starred": True, "distance": 2000.0}
        raise AssertionError(path)

    from strava_mcp.db.repositories.segments import SegmentsRepository
    from strava_mcp.sync.resources.segments import SegmentsSyncer

    SegmentsSyncer(FakeStravaClient(starred_handler), SegmentsRepository(conn)).run_starred()
    assert conn.execute("SELECT starred FROM segments WHERE id=660001").fetchone()[0] == 1

    # A later encountered insert must NOT downgrade the starred row.
    SegmentsRepository(conn).insert_encountered({"id": 660001, "name": "Tabor Climb"})
    conn.commit()
    assert conn.execute("SELECT starred FROM segments WHERE id=660001").fetchone()[0] == 1
