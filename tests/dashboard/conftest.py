"""Shared helpers for dashboard tests (real temp SQLite, no live Strava)."""

from __future__ import annotations

import sqlite3
from typing import Any

from strava_mcp.db.repositories.activities import ActivitiesRepository


def make_activity(
    activity_id: int,
    *,
    sport_type: str = "Ride",
    start_date: str = "2021-05-04T08:00:00Z",
    name: str | None = None,
    distance: float = 20000.0,
    moving_time: int = 3600,
    total_elevation_gain: float = 200.0,
    average_heartrate: float | None = 140.0,
    average_watts: float | None = 180.0,
    segment_efforts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": activity_id,
        "sport_type": sport_type,
        "start_date": start_date,
        "start_date_local": start_date,
        "name": name or f"Activity {activity_id}",
        "distance": distance,
        "moving_time": moving_time,
        "elapsed_time": moving_time + 120,
        "total_elevation_gain": total_elevation_gain,
        "average_heartrate": average_heartrate,
        "average_watts": average_watts,
        "segment_efforts": segment_efforts or [],
    }


def enrich(
    conn: sqlite3.Connection,
    detail: dict[str, Any],
    *,
    laps: list[dict[str, Any]] | None = None,
    zones: list[dict[str, Any]] | None = None,
    streams: dict[str, Any] | None = None,
) -> None:
    """Fully enrich an activity (visible) with streams via the repository."""
    ActivitiesRepository(conn).enrich(
        detail=detail,
        laps=laps or [],
        zones=zones or [],
        streams=streams or {"time": {"data": [0, 1, 2]}, "heartrate": {"data": [120, 130, 140]}},
    )


def enrich_without_streams(conn: sqlite3.Connection, detail: dict[str, Any]) -> None:
    """Make an activity visible but with no streams row (edge case for the detail view)."""
    repo = ActivitiesRepository(conn)
    repo.insert_summary(detail)
    conn.execute(
        "UPDATE activities SET enriched_at = ?, detail_json = ? WHERE id = ?",
        ("2021-06-01T00:00:00Z", __import__("json").dumps(detail), detail["id"]),
    )
    conn.commit()


def set_sync_state(conn: sqlite3.Connection, **fields: Any) -> None:
    """Insert/replace the single sync_state row with the given fields."""
    base: dict[str, Any] = {
        "id": 1,
        "phase": "BACKFILL",
        "backfill_frontier_epoch": None,
        "newest_synced_epoch": None,
        "backfill_complete": 0,
        "last_poll_at": None,
        "cooldown_until": None,
        "rate_limit_json": None,
        "run_log_json": None,
        "updated_at": "2021-06-01T00:00:00Z",
    }
    base.update(fields)
    cols = ", ".join(base)
    placeholders = ", ".join("?" for _ in base)
    conn.execute(
        f"INSERT OR REPLACE INTO sync_state ({cols}) VALUES ({placeholders})",
        tuple(base.values()),
    )
    conn.commit()
