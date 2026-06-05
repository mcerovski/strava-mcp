"""Sync observability + control tools: ``sync_status`` (US3), ``sync_now`` (US7).

``sync_status`` is a pure read over ``sync_state`` plus cheap COUNTs. It computes
``fully_synced`` from DB truth (``backfill_complete`` AND every activity carries
streams) without importing the worker — preserving the pure-reader boundary.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strava_mcp.mcp.tools import reader


class _Trigger:
    """Minimal interface for nudging the worker (a ``threading.Event``)."""

    def set(self) -> None: ...  # pragma: no cover - protocol stub


def _iso(epoch: int | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _count(conn: Any, table: str, where: str = "") -> int:
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return int(conn.execute(sql).fetchone()[0])


def sync_status(db_path: Path | str) -> dict[str, Any]:
    """Report worker phase, frontier, progress, counts, rate budget, cooldown."""
    with reader(db_path) as conn:
        row = conn.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
        state: dict[str, Any] = (
            dict(row) if row is not None else {"phase": "BOOTSTRAP", "backfill_complete": 0}
        )

        activities = _count(conn, "activities")
        enriched = _count(conn, "activities", "enriched_at IS NOT NULL")
        streams = _count(conn, "activity_streams")
        gear = _count(conn, "gear")
        routes = _count(conn, "routes")
        starred = _count(conn, "segments", "starred = 1")

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


def sync_now(db_path: Path | str, trigger: _Trigger | None = None) -> dict[str, Any]:
    """Nudge the worker to run the forward POLL immediately (US7).

    Signals the worker via ``trigger`` (a ``threading.Event`` shared with the
    server) and reports the most recent POLL outcome from the run log. Never
    calls Strava and never mutates mirrored data (insert-only is the worker's
    job); a no-op trigger means the server had no running worker.
    """
    triggered = False
    if trigger is not None:
        trigger.set()
        triggered = True

    with reader(db_path) as conn:
        row = conn.execute("SELECT run_log_json FROM sync_state WHERE id = 1").fetchone()

    outcome = "no poll has run yet"
    if row is not None and row["run_log_json"]:
        log = json.loads(row["run_log_json"])
        polls = [e for e in log if e.get("phase") == "POLL"]
        if polls:
            outcome = polls[-1].get("outcome", outcome)

    return {"triggered": triggered, "outcome": outcome}
