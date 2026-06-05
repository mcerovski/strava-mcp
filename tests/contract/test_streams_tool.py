"""T042 [US5] Contract: get_activity_streams incl. key-filtering and not_yet_synced."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from strava_mcp.db.repositories.activities import ActivitiesRepository
from strava_mcp.mcp.tools.streams import get_activity_streams
from strava_mcp.sync.resources.activities import ActivitiesSyncer

from tests.conftest import FakeStravaClient
from tests.fixtures import load


def _handler(path: str, params: dict[str, object]) -> object:
    suffix = path.split("/activities/900003")[-1]
    if suffix == "":
        return load("activity_detail")
    if suffix == "/streams":
        return load("streams")
    return []


def _enriched(conn: sqlite3.Connection) -> None:
    repo = ActivitiesRepository(conn)
    repo.insert_summary({"id": 900003, "start_date": "2021-05-30T08:00:00Z"})
    ActivitiesSyncer(FakeStravaClient(_handler), repo).enrich(900003)


def test_streams_returns_all_types(conn: sqlite3.Connection, db_path: Path) -> None:
    _enriched(conn)
    result = get_activity_streams(db_path, 900003)
    assert result["activity_id"] == 900003
    assert set(result["streams"]) >= {"time", "distance", "heartrate", "watts", "latlng"}


def test_streams_key_filtering(conn: sqlite3.Connection, db_path: Path) -> None:
    _enriched(conn)
    result = get_activity_streams(db_path, 900003, keys=["heartrate", "watts"])
    assert set(result["streams"]) == {"heartrate", "watts"}
    assert result["types"] == list(result["streams"].keys())


def test_streams_not_yet_synced_when_pending(conn: sqlite3.Connection, db_path: Path) -> None:
    ActivitiesRepository(conn).insert_summary({"id": 77, "start_date": "2021-01-01T00:00:00Z"})
    assert get_activity_streams(db_path, 77) == {"status": "not_yet_synced", "id": 77}


def test_streams_not_found_when_absent(db_path: Path, conn: sqlite3.Connection) -> None:
    assert get_activity_streams(db_path, 4242) == {"status": "not_found", "id": 4242}
