"""T028 [US3] Contract: list_activities filters, get_activity, sync_status."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from strava_mcp.db.repositories.activities import ActivitiesRepository, parse_epoch
from strava_mcp.mcp.tools.activities import get_activity, list_activities
from strava_mcp.mcp.tools.sync import sync_status
from strava_mcp.sync.state import SyncState

_ACTS = [
    {
        "id": 1,
        "name": "R1",
        "sport_type": "Run",
        "start_date": "2021-05-01T08:00:00Z",
        "distance": 5000.0,
    },
    {
        "id": 2,
        "name": "Ride1",
        "sport_type": "Ride",
        "start_date": "2021-05-10T08:00:00Z",
        "distance": 30000.0,
    },
    {
        "id": 3,
        "name": "R2",
        "sport_type": "Run",
        "start_date": "2021-05-20T08:00:00Z",
        "distance": 10000.0,
    },
]


def _seed(conn: sqlite3.Connection, *, enrich: set[int]) -> None:
    repo = ActivitiesRepository(conn)
    for a in _ACTS:
        repo.insert_summary(a)
        if a["id"] in enrich:
            conn.execute(
                "UPDATE activities SET enriched_at = ? WHERE id = ?",
                ("2021-06-01T00:00:00Z", a["id"]),
            )
    conn.commit()


def test_list_only_returns_enriched_newest_first(conn: sqlite3.Connection, db_path: Path) -> None:
    _seed(conn, enrich={1, 3})  # id 2 stays pending → invisible
    result = list_activities(db_path)
    assert [r["id"] for r in result] == [3, 1]  # newest first, id 2 excluded


def test_list_filters_by_sport_and_date(conn: sqlite3.Connection, db_path: Path) -> None:
    _seed(conn, enrich={1, 2, 3})
    runs = list_activities(db_path, sport_type="Run")
    assert [r["id"] for r in runs] == [3, 1]

    after = parse_epoch("2021-05-05T00:00:00Z")
    before = parse_epoch("2021-05-15T00:00:00Z")
    windowed = list_activities(db_path, after=after, before=before)
    assert [r["id"] for r in windowed] == [2]

    # ISO strings accepted too.
    windowed_iso = list_activities(
        db_path, after="2021-05-05T00:00:00Z", before="2021-05-15T00:00:00Z"
    )
    assert [r["id"] for r in windowed_iso] == [2]


def test_get_activity_status_signals(conn: sqlite3.Connection, db_path: Path) -> None:
    _seed(conn, enrich={1})
    assert get_activity(db_path, 1)["id"] == 1  # enriched → full detail
    assert get_activity(db_path, 2) == {"status": "not_yet_synced", "id": 2}  # pending
    assert get_activity(db_path, 999) == {"status": "not_found", "id": 999}  # absent


def test_sync_status_reports_fields(conn: sqlite3.Connection, db_path: Path) -> None:
    _seed(conn, enrich={1, 3})
    state = SyncState(conn)
    state.ensure()
    state.set_phase("BACKFILL")
    state.set_frontier(parse_epoch("2021-05-01T08:00:00Z"))
    state.set_rate_limit({"read_15min": {"used": 5, "limit": 100}})

    status = sync_status(db_path)
    assert status["phase"] == "BACKFILL"
    assert status["frontier_date"] == "2021-05-01T08:00:00Z"
    assert status["counts"]["activities"] == 3
    assert status["counts"]["enriched"] == 2
    assert status["fully_synced"] is False
    assert status["rate_limit"]["read_15min"]["used"] == 5
    assert 0 <= status["percent_complete"] <= 100
