"""T063 [US8] Contract: summarize_training weekly/monthly + sport filter correctness."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from strava_mcp.db.repositories.activities import ActivitiesRepository
from strava_mcp.mcp.tools.summaries import summarize_training


def _enriched(conn: sqlite3.Connection, acts: list[dict]) -> None:
    repo = ActivitiesRepository(conn)
    for a in acts:
        repo.insert_summary(a)
        conn.execute(
            "UPDATE activities SET enriched_at = ? WHERE id = ?",
            ("2021-07-01T00:00:00Z", a["id"]),
        )
    conn.commit()


_ACTS = [
    # Week of 2021-05-03 (Mon) — two rides.
    {
        "id": 1,
        "sport_type": "Ride",
        "start_date": "2021-05-04T08:00:00Z",
        "distance": 20000.0,
        "moving_time": 3600,
        "total_elevation_gain": 200.0,
    },
    {
        "id": 2,
        "sport_type": "Ride",
        "start_date": "2021-05-06T08:00:00Z",
        "distance": 30000.0,
        "moving_time": 5400,
        "total_elevation_gain": 300.0,
    },
    # Week of 2021-05-10 (Mon) — one run.
    {
        "id": 3,
        "sport_type": "Run",
        "start_date": "2021-05-12T08:00:00Z",
        "distance": 10000.0,
        "moving_time": 3000,
        "total_elevation_gain": 80.0,
    },
]


def test_weekly_rollups_match_underlying(conn: sqlite3.Connection, db_path: Path) -> None:
    _enriched(conn, _ACTS)
    weekly = summarize_training(db_path, period="weekly")
    by_week = {r["period_start"]: r for r in weekly}

    assert by_week["2021-05-03"]["count"] == 2
    assert by_week["2021-05-03"]["distance"] == 50000.0
    assert by_week["2021-05-03"]["moving_time"] == 9000
    assert by_week["2021-05-03"]["total_elevation_gain"] == 500.0
    assert by_week["2021-05-10"]["count"] == 1


def test_monthly_rollup(conn: sqlite3.Connection, db_path: Path) -> None:
    _enriched(conn, _ACTS)
    monthly = summarize_training(db_path, period="monthly")
    assert len(monthly) == 1
    assert monthly[0]["period_start"] == "2021-05-01"
    assert monthly[0]["count"] == 3
    assert monthly[0]["distance"] == 60000.0


def test_sport_filter(conn: sqlite3.Connection, db_path: Path) -> None:
    _enriched(conn, _ACTS)
    rides = summarize_training(db_path, period="monthly", sport_type="Ride")
    assert rides[0]["count"] == 2
    assert rides[0]["distance"] == 50000.0
    runs = summarize_training(db_path, period="monthly", sport_type="Run")
    assert runs[0]["count"] == 1


def test_only_enriched_counted(conn: sqlite3.Connection, db_path: Path) -> None:
    repo = ActivitiesRepository(conn)
    repo.insert_summary(
        {"id": 99, "sport_type": "Ride", "start_date": "2021-05-04T08:00:00Z", "distance": 9999.0}
    )
    # Not enriched → excluded.
    assert summarize_training(db_path, period="monthly") == []
