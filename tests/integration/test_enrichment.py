"""T036 [US4] Single-transaction enrichment incl. streams; enriched_at last.

No partial exposure: an activity missing streams stays not_yet_synced; efforts
are populated from embedded activity data.
"""

from __future__ import annotations

import sqlite3

import pytest
from strava_mcp.db.repositories.activities import ActivitiesRepository
from strava_mcp.sync.resources.activities import ActivitiesSyncer

from tests.conftest import FakeStravaClient
from tests.fixtures import load


def _enrich_handler(path: str, params: dict[str, object]) -> object:
    if path == "/activities/900003":
        return load("activity_detail")
    if path == "/activities/900003/laps":
        return load("laps")
    if path == "/activities/900003/zones":
        return load("zones")
    if path == "/activities/900003/streams":
        return load("streams")
    raise AssertionError(path)


def test_enrichment_writes_all_facets_and_stamps_last(conn: sqlite3.Connection) -> None:
    repo = ActivitiesRepository(conn)
    repo.insert_summary(
        {
            "id": 900003,
            "name": "Morning Ride",
            "sport_type": "Ride",
            "start_date": "2021-05-30T08:00:00Z",
            "distance": 32000.0,
        }
    )
    # Pre-enrichment: summary exists but invisible.
    assert repo.status(900003) == "pending"

    client = FakeStravaClient(_enrich_handler)
    ActivitiesSyncer(client, repo).enrich(900003)

    # FR-013: exactly four read requests per activity — detail, laps, zones,
    # streams — and never comments or kudos.
    paths = [p for p, _ in client.calls]
    assert paths == [
        "/activities/900003",
        "/activities/900003/laps",
        "/activities/900003/zones",
        "/activities/900003/streams",
    ]
    assert not any("/comments" in p or "/kudos" in p for p in paths)

    # Visible only now, with all facets + streams present.
    assert repo.status(900003) == "enriched"
    assert (
        conn.execute("SELECT enriched_at FROM activities WHERE id=900003").fetchone()[0] is not None
    )
    assert conn.execute("SELECT COUNT(*) FROM laps WHERE activity_id=900003").fetchone()[0] == 2
    assert (
        conn.execute("SELECT COUNT(*) FROM activity_zones WHERE activity_id=900003").fetchone()[0]
        == 2
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM activity_streams WHERE activity_id=900003").fetchone()[0]
        == 1
    )
    # Embedded efforts populated (segment_efforts[] + best_efforts[]).
    assert (
        conn.execute("SELECT COUNT(*) FROM segment_efforts WHERE activity_id=900003").fetchone()[0]
        == 2
    )
    # detail_json upgraded to DetailedActivity (has description).
    detail = repo.get_detail(900003)
    assert detail is not None and "description" in detail


def test_enrichment_without_streams_never_becomes_visible(conn: sqlite3.Connection) -> None:
    repo = ActivitiesRepository(conn)
    repo.insert_summary({"id": 5, "start_date": "2021-01-01T00:00:00Z"})
    with pytest.raises(ValueError):
        repo.enrich(detail={"id": 5}, laps=[], zones=[], streams=None)
    # Still invisible; no enriched_at, no streams row.
    assert repo.status(5) == "pending"
    assert (
        conn.execute("SELECT COUNT(*) FROM activity_streams WHERE activity_id=5").fetchone()[0] == 0
    )


def test_enrichment_rolls_back_on_failure(conn: sqlite3.Connection) -> None:
    """A failure mid-enrichment leaves nothing stamped (atomic unit)."""
    repo = ActivitiesRepository(conn)
    repo.insert_summary({"id": 7, "start_date": "2021-01-01T00:00:00Z"})
    # A lap missing its id raises inside the transaction → rollback.
    with pytest.raises(KeyError):
        repo.enrich(
            detail={"id": 7},
            laps=[{"lap_index": 1}],  # missing "id"
            zones=[],
            streams={"time": {"data": [0]}},
        )
    assert repo.status(7) == "pending"
    assert (
        conn.execute("SELECT COUNT(*) FROM activity_streams WHERE activity_id=7").fetchone()[0] == 0
    )
