"""T048 [US6] Contract: gear/routes/segments tools (starred-vs-encountered, no fetch)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from strava_mcp.db.repositories.activities import ActivitiesRepository
from strava_mcp.db.repositories.gear import GearRepository
from strava_mcp.db.repositories.routes import RoutesRepository
from strava_mcp.db.repositories.segments import SegmentsRepository
from strava_mcp.mcp.tools.gear import get_gear, list_gear
from strava_mcp.mcp.tools.routes import get_route, list_routes
from strava_mcp.mcp.tools.segments import (
    get_segment,
    list_segment_efforts,
    list_starred_segments,
)
from strava_mcp.sync.resources.activities import ActivitiesSyncer

from tests.conftest import FakeStravaClient
from tests.fixtures import load


def _seed(conn: sqlite3.Connection) -> None:
    GearRepository(conn).save(load("gear"), gear_type="bike")
    RoutesRepository(conn).save(load("route"))
    SegmentsRepository(conn).upsert_starred(load("segment"))  # id 550010, starred
    # Enrich an activity → encountered segment 660001 + efforts.
    repo = ActivitiesRepository(conn)
    repo.insert_summary({"id": 900003, "start_date": "2021-05-30T08:00:00Z"})

    def handler(path: str, params: dict[str, object]) -> object:
        suffix = path.split("/activities/900003")[-1]
        if suffix == "":
            return load("activity_detail")
        if suffix == "/streams":
            return load("streams")
        return []

    ActivitiesSyncer(FakeStravaClient(handler), repo).enrich(900003)


def test_gear_tools(conn: sqlite3.Connection, db_path: Path) -> None:
    _seed(conn)
    assert {g["id"] for g in list_gear(db_path)} == {"b1234"}
    assert get_gear(db_path, "b1234")["brand_name"] == "Trek"
    assert get_gear(db_path, "nope") == {"status": "not_found", "id": "nope"}


def test_route_tools(conn: sqlite3.Connection, db_path: Path) -> None:
    _seed(conn)
    assert {r["id_str"] for r in list_routes(db_path)} == {"770099"}
    assert "map" in get_route(db_path, "770099")
    assert get_route(db_path, "x") == {"status": "not_found", "id": "x"}


def test_segment_tools_starred_vs_encountered(conn: sqlite3.Connection, db_path: Path) -> None:
    _seed(conn)
    starred = list_starred_segments(db_path)
    assert [s["id"] for s in starred] == [550010]

    # Starred → full detail (has effort_count); encountered → embedded summary.
    assert get_segment(db_path, 550010)["effort_count"] == 120
    encountered = get_segment(db_path, 660001)
    assert encountered["id"] == 660001
    assert encountered.get("effort_count") is None  # summary, not full detail

    assert get_segment(db_path, 999999) == {"status": "not_found", "id": 999999}


def test_list_segment_efforts(conn: sqlite3.Connection, db_path: Path) -> None:
    _seed(conn)
    efforts = list_segment_efforts(db_path, 660001)
    assert len(efforts) == 1
    assert efforts[0]["id"] == 8800001
