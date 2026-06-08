"""Read-only data access for the dashboard.

Composes the existing ``repositories/`` layer over per-call read-only SQLite
connections (no ad-hoc SQL leaks into handlers). This module imports neither
``strava_mcp.client`` nor ``strava_mcp.sync`` — it is a pure reader.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from strava_mcp.db.repositories.activities import ActivitiesRepository
from strava_mcp.db.repositories.athlete import AthleteRepository
from strava_mcp.db.repositories.gear import GearRepository
from strava_mcp.db.repositories.routes import RoutesRepository
from strava_mcp.db.repositories.segments import SegmentsRepository
from strava_mcp.db.repositories.streams import StreamsRepository
from strava_mcp.db.repositories.sync_state import SyncStateRepository

PAGE_SIZE = 50


@contextmanager
def reader(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """Open a read-only connection for the duration of one request."""
    from strava_mcp.db import engine

    conn = engine.read_only_connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


# --- athlete header --------------------------------------------------------
def athlete_header(db_path: Path | str) -> dict[str, Any] | None:
    """The athlete profile/stats for the page header, or None on an empty mirror."""
    with reader(db_path) as conn:
        return AthleteRepository(conn).read()


# --- activity list (US1) ---------------------------------------------------
def list_activities_page(
    db_path: Path | str,
    *,
    after_epoch: int | None = None,
    before_epoch: int | None = None,
    sport_type: str | None = None,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> dict[str, Any]:
    """A page of enriched activities plus the total count (for the pager)."""
    page = max(1, page)
    offset = (page - 1) * page_size
    with reader(db_path) as conn:
        repo = ActivitiesRepository(conn)
        items = repo.list_page(
            after_epoch=after_epoch,
            before_epoch=before_epoch,
            sport_type=sport_type,
            limit=page_size,
            offset=offset,
        )
        total = repo.count_page(
            after_epoch=after_epoch, before_epoch=before_epoch, sport_type=sport_type
        )
    pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


def sport_types(db_path: Path | str) -> list[str]:
    """Distinct sport types across enriched activities (for the filter control)."""
    with reader(db_path) as conn:
        return ActivitiesRepository(conn).distinct_sport_types()


# --- activity detail (US2) -------------------------------------------------
def activity_detail(db_path: Path | str, activity_id: int) -> dict[str, Any] | None:
    """Full detail view for one enriched activity, or None if absent/not enriched."""
    with reader(db_path) as conn:
        acts = ActivitiesRepository(conn)
        detail = acts.get_detail(activity_id)
        if detail is None:
            return None
        laps = acts.laps(activity_id)
        zones = acts.zones(activity_id)
        efforts = SegmentsRepository(conn).efforts_for_activity(activity_id)
        streams = StreamsRepository(conn).read(activity_id)
    return {
        "detail": detail,
        "laps": laps,
        "zones": zones,
        "segment_efforts": efforts,
        "streams": streams,  # None if no streams row
    }


# --- timeline (US3) --------------------------------------------------------
def _previous_period_start(d: date, period: str) -> date:
    """The bucket start immediately before ``d`` for the given period."""
    if period == "weekly":
        return date.fromordinal(d.toordinal() - 7)
    if period == "monthly":
        year, month = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
        return date(year, month, 1)
    # yearly
    return date(d.year - 1, 1, 1)


def _zero_bucket(period_start: str) -> dict[str, Any]:
    return {
        "period_start": period_start,
        "count": 0,
        "distance": 0,
        "moving_time": 0,
        "total_elevation_gain": 0,
    }


def timeline(
    db_path: Path | str,
    *,
    period: str = "monthly",
    sport_type: str | None = None,
) -> list[dict[str, Any]]:
    """Timeline buckets (newest first) with empty periods filled as zero buckets.

    Filling the gaps between the first and last populated period keeps training
    gaps visible (spec US3 scenario 3).
    """
    with reader(db_path) as conn:
        rollup = ActivitiesRepository(conn).training_rollup(period=period, sport_type=sport_type)
    if not rollup:
        return []
    by_start = {r["period_start"]: r for r in rollup}
    newest = date.fromisoformat(rollup[0]["period_start"])
    oldest = date.fromisoformat(rollup[-1]["period_start"])
    out: list[dict[str, Any]] = []
    cursor = newest
    while cursor >= oldest:
        key = cursor.isoformat()
        out.append(by_start.get(key) or _zero_bucket(key))
        cursor = _previous_period_start(cursor, period)
    return out


# --- sync progress (US4) ---------------------------------------------------
def _iso(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync_progress(db_path: Path | str) -> dict[str, Any]:
    """Current persisted sync state + counts (computed like the sync_status tool).

    Read at request time; there is no auto-refresh (spec FR-012). Shows the last
    persisted state if the worker is not running.
    """
    with reader(db_path) as conn:
        state = SyncStateRepository(conn).snapshot()
        acts = ActivitiesRepository(conn)
        activities = acts.count()
        enriched = acts.count_enriched()
        streams = StreamsRepository(conn).count()
        gear = GearRepository(conn).count()
        routes = RoutesRepository(conn).count()
        starred = SegmentsRepository(conn).count_starred()

    backfill_complete = bool(state.get("backfill_complete"))
    fully_synced = backfill_complete and streams >= activities
    if backfill_complete:
        percent = 100.0
    elif activities:
        percent = round(enriched / activities * 100, 1)
    else:
        percent = 0.0

    rate_limit = state.get("rate_limit_json")
    return {
        "phase": state.get("phase"),
        "frontier_date": _iso(state.get("backfill_frontier_epoch")),
        "newest_synced_date": _iso(state.get("newest_synced_epoch")),
        "percent_complete": percent,
        "fully_synced": fully_synced,
        "backfill_complete": backfill_complete,
        "last_poll_at": state.get("last_poll_at"),
        "counts": {
            "activities": activities,
            "enriched": enriched,
            "streams": streams,
            "gear": gear,
            "routes": routes,
            "starred_segments": starred,
        },
        "rate_limit": json.loads(rate_limit) if rate_limit else None,
        "cooldown_until": state.get("cooldown_until"),
    }
