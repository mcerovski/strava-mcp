"""Handler tests: T012 [US1] list, T018 [US2] detail, T024 [US3] timeline, T029 [US4] sync."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from strava_mcp.dashboard import handlers

from .conftest import enrich, enrich_without_streams, make_activity, set_sync_state


# --- US1 list -------------------------------------------------------------
def test_list_renders_rows_and_count(conn: sqlite3.Connection, db_path: Path) -> None:
    enrich(conn, make_activity(1, name="Morning Ride"))
    enrich(conn, make_activity(2, name="Evening Run", sport_type="Run"))
    status, html = handlers.handle_list(db_path, {})
    assert status == 200
    assert "Morning Ride" in html and "Evening Run" in html
    assert "2 activities" in html
    assert 'href="/activity/1"' in html


def test_list_empty_state(conn: sqlite3.Connection, db_path: Path) -> None:  # noqa: ARG001
    status, html = handlers.handle_list(db_path, {})
    assert status == 200
    assert "No activities match" in html


def test_list_sport_filter(conn: sqlite3.Connection, db_path: Path) -> None:
    enrich(conn, make_activity(1, name="A Run", sport_type="Run"))
    enrich(conn, make_activity(2, name="A Ride", sport_type="Ride"))
    _, html = handlers.handle_list(db_path, {"sport_type": ["Run"]})
    assert "A Run" in html and "A Ride" not in html


# --- US2 detail -----------------------------------------------------------
def test_detail_renders_sections(conn: sqlite3.Connection, db_path: Path) -> None:
    effort = {
        "id": 9001,
        "elapsed_time": 90,
        "distance": 500.0,
        "segment": {"id": 7, "name": "Test Climb", "distance": 500.0},
    }
    detail = make_activity(1, name="Big Ride", segment_efforts=[effort])
    laps = [{"id": 11, "lap_index": 1, "name": "Lap 1", "distance": 10000.0, "moving_time": 1800}]
    zones = [
        {
            "type": "heartrate",
            "distribution_buckets": [
                {"min": 0, "max": 120, "time": 600},
                {"min": 120, "max": 160, "time": 1200},
            ],
        }
    ]
    streams = {
        "time": {"data": [0, 1, 2, 3]},
        "heartrate": {"data": [120, 130, 140, 150]},
        "watts": {"data": [150, 200, 210, 190]},
    }
    enrich(conn, detail, laps=laps, zones=zones, streams=streams)

    status, html = handlers.handle_detail(db_path, 1)
    assert status == 200
    assert "Big Ride" in html
    assert "Laps" in html and "Lap 1" in html
    assert "Segment efforts" in html and "Test Climb" in html
    assert "Zone distribution" in html
    assert "<polyline" in html  # graphs rendered


def test_detail_no_streams_note(conn: sqlite3.Connection, db_path: Path) -> None:
    enrich_without_streams(conn, make_activity(5, name="Manual Entry"))
    status, html = handlers.handle_detail(db_path, 5)
    assert status == 200
    assert "No stream data" in html
    assert "<polyline" not in html


def test_detail_missing_is_404(conn: sqlite3.Connection, db_path: Path) -> None:  # noqa: ARG001
    status, html = handlers.handle_detail(db_path, 999)
    assert status == 404
    assert "not yet synced" in html


def test_detail_pending_is_404(conn: sqlite3.Connection, db_path: Path) -> None:
    from strava_mcp.db.repositories.activities import ActivitiesRepository

    ActivitiesRepository(conn).insert_summary(make_activity(8))  # pending, not enriched
    conn.commit()
    status, _ = handlers.handle_detail(db_path, 8)
    assert status == 404


# --- US3 timeline ---------------------------------------------------------
def test_timeline_default_and_period_switch(conn: sqlite3.Connection, db_path: Path) -> None:
    enrich(conn, make_activity(1, start_date="2021-01-10T08:00:00Z"))
    enrich(conn, make_activity(2, start_date="2021-03-10T08:00:00Z"))

    status, html = handlers.handle_timeline(db_path, {})  # default monthly
    assert status == 200
    assert "2021-02-01" in html  # zero bucket visible (gap)

    _, yearly = handlers.handle_timeline(db_path, {"period": ["year"]})
    assert "2021-01-01" in yearly


# --- US4 sync -------------------------------------------------------------
def test_sync_states_and_no_autorefresh(conn: sqlite3.Connection, db_path: Path) -> None:
    enrich(conn, make_activity(1))
    set_sync_state(conn, phase="BACKFILL", cooldown_until="2021-06-01T00:15:00Z")
    status, html = handlers.handle_sync(db_path)
    assert status == 200
    assert "Sync progress" in html
    assert "BACKFILL" in html
    assert "2021-06-01T00:15:00Z" in html
    # No auto-refresh in v1 (FR-012): no meta-refresh and no client script.
    assert "http-equiv" not in html.lower()
    assert "<script" not in html.lower()


def test_sync_fully_synced_badge(conn: sqlite3.Connection, db_path: Path) -> None:
    enrich(conn, make_activity(1))
    set_sync_state(conn, phase="POLL", backfill_complete=1)
    _, html = handlers.handle_sync(db_path)
    assert "fully synced" in html
