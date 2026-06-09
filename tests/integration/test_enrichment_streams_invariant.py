"""T046 [US5] Regression guard: enrichment persists streams before stamping enriched_at.

The visibility invariant (R8, Constitution III) requires that no activity is ever
visible (``enriched_at`` set) without a streams row. This guard pins that down:
enrichment without streams must never stamp, and a stamped activity always has a
streams row.
"""

from __future__ import annotations

import sqlite3

import pytest
from strava_mcp.db.repositories.activities import ActivitiesRepository


def _all_enriched_have_streams(conn: sqlite3.Connection) -> bool:
    orphans = conn.execute(
        "SELECT COUNT(*) FROM activities a "
        "WHERE a.enriched_at IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM activity_streams s WHERE s.activity_id = a.id)"
    ).fetchone()[0]
    return orphans == 0


def test_streamless_enrichment_cannot_stamp(conn: sqlite3.Connection) -> None:
    repo = ActivitiesRepository(conn)
    repo.insert_summary({"id": 1, "start_date": "2021-01-01T00:00:00Z"})
    with pytest.raises(ValueError):
        repo.enrich(detail={"id": 1}, laps=[], zones=[], streams=None)
    assert _all_enriched_have_streams(conn)  # no orphan stamped


def test_enriched_activity_always_has_streams_row(conn: sqlite3.Connection) -> None:
    repo = ActivitiesRepository(conn)
    repo.insert_summary({"id": 2, "start_date": "2021-01-01T00:00:00Z"})
    repo.enrich(
        detail={"id": 2},
        laps=[],
        zones=[],
        streams={"time": {"data": [0, 1]}},
    )
    assert conn.execute("SELECT enriched_at FROM activities WHERE id=2").fetchone()[0] is not None
    assert _all_enriched_have_streams(conn)
