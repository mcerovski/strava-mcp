"""T011 [US1], T023 [US3], T028 [US4] dashboard read-layer correctness."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from strava_mcp.dashboard import queries
from strava_mcp.db.repositories.activities import parse_epoch

from .conftest import enrich, make_activity, set_sync_state


# --- US1 list -------------------------------------------------------------
def test_list_pagination_and_order(conn: sqlite3.Connection, db_path: Path) -> None:
    for i in range(1, 6):
        enrich(conn, make_activity(i, start_date=f"2021-05-0{i}T08:00:00Z"))

    p1 = queries.list_activities_page(db_path, page=1, page_size=2)
    assert p1["total"] == 5
    assert p1["pages"] == 3
    assert [it["id"] for it in p1["items"]] == [5, 4]  # newest first

    p3 = queries.list_activities_page(db_path, page=3, page_size=2)
    assert [it["id"] for it in p3["items"]] == [1]


def test_list_filters(conn: sqlite3.Connection, db_path: Path) -> None:
    enrich(conn, make_activity(1, sport_type="Run", start_date="2021-05-01T08:00:00Z"))
    enrich(conn, make_activity(2, sport_type="Ride", start_date="2021-05-10T08:00:00Z"))
    enrich(conn, make_activity(3, sport_type="Run", start_date="2021-05-20T08:00:00Z"))

    runs = queries.list_activities_page(db_path, sport_type="Run")
    assert [it["id"] for it in runs["items"]] == [3, 1]

    windowed = queries.list_activities_page(
        db_path,
        after_epoch=parse_epoch("2021-05-05T00:00:00Z"),
        before_epoch=parse_epoch("2021-05-15T00:00:00Z"),
    )
    assert [it["id"] for it in windowed["items"]] == [2]


def test_list_excludes_pending(conn: sqlite3.Connection, db_path: Path) -> None:
    from strava_mcp.db.repositories.activities import ActivitiesRepository

    enrich(conn, make_activity(1))
    ActivitiesRepository(conn).insert_summary(make_activity(2))  # pending → invisible
    conn.commit()
    result = queries.list_activities_page(db_path)
    assert [it["id"] for it in result["items"]] == [1]


# --- US3 timeline ---------------------------------------------------------
def test_timeline_yearly_and_gap_fill(conn: sqlite3.Connection, db_path: Path) -> None:
    enrich(conn, make_activity(1, start_date="2021-01-10T08:00:00Z", distance=10000.0))
    enrich(conn, make_activity(2, start_date="2021-03-10T08:00:00Z", distance=20000.0))

    monthly = queries.timeline(db_path, period="monthly")
    starts = [b["period_start"] for b in monthly]
    # Newest first, with the empty February filled as a zero bucket.
    assert starts == ["2021-03-01", "2021-02-01", "2021-01-01"]
    feb = next(b for b in monthly if b["period_start"] == "2021-02-01")
    assert feb["count"] == 0 and feb["distance"] == 0

    yearly = queries.timeline(db_path, period="yearly")
    assert [b["period_start"] for b in yearly] == ["2021-01-01"]
    assert yearly[0]["count"] == 2 and yearly[0]["distance"] == 30000.0


def test_timeline_empty_mirror(conn: sqlite3.Connection, db_path: Path) -> None:  # noqa: ARG001
    assert queries.timeline(db_path, period="monthly") == []


# --- US4 sync progress ----------------------------------------------------
def test_sync_progress_backfill(conn: sqlite3.Connection, db_path: Path) -> None:
    enrich(conn, make_activity(1))
    from strava_mcp.db.repositories.activities import ActivitiesRepository

    ActivitiesRepository(conn).insert_summary(make_activity(2))  # pending
    conn.commit()
    set_sync_state(
        conn,
        phase="BACKFILL",
        backfill_frontier_epoch=parse_epoch("2021-05-01T00:00:00Z"),
        backfill_complete=0,
        cooldown_until="2021-06-01T00:15:00Z",
    )

    progress = queries.sync_progress(db_path)
    assert progress["phase"] == "BACKFILL"
    assert progress["counts"]["activities"] == 2
    assert progress["counts"]["enriched"] == 1
    assert progress["percent_complete"] == 50.0
    assert progress["fully_synced"] is False
    assert progress["frontier_date"] == "2021-05-01T00:00:00Z"
    assert progress["cooldown_until"] == "2021-06-01T00:15:00Z"


def test_sync_progress_fully_synced(conn: sqlite3.Connection, db_path: Path) -> None:
    enrich(conn, make_activity(1))
    set_sync_state(conn, phase="POLL", backfill_complete=1, last_poll_at="2021-06-02T00:00:00Z")
    progress = queries.sync_progress(db_path)
    assert progress["fully_synced"] is True
    assert progress["percent_complete"] == 100.0
    assert progress["last_poll_at"] == "2021-06-02T00:00:00Z"
