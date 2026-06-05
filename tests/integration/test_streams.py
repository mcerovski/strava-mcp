"""T041 [US5] Streams retrievable per type + fully_synced flips only with streams."""

from __future__ import annotations

import sqlite3

from strava_mcp.db.repositories.activities import ActivitiesRepository
from strava_mcp.db.repositories.streams import StreamsRepository
from strava_mcp.sync.resources.activities import ActivitiesSyncer
from strava_mcp.sync.state import SyncState

from tests.conftest import FakeStravaClient
from tests.fixtures import load


def _handler(path: str, params: dict[str, object]) -> object:
    suffix = path.split("/activities/900003")[-1]
    if suffix == "":
        return load("activity_detail")
    if suffix == "/streams":
        return load("streams")
    return []


def test_streams_stored_and_readable_per_type(conn: sqlite3.Connection) -> None:
    repo = ActivitiesRepository(conn)
    repo.insert_summary({"id": 900003, "start_date": "2021-05-30T08:00:00Z"})
    ActivitiesSyncer(FakeStravaClient(_handler), repo).enrich(900003)

    streams = StreamsRepository(conn).read(900003)
    assert streams is not None
    assert set(streams["types"]) >= {"time", "heartrate", "watts"}
    assert streams["streams"]["heartrate"]["data"] == [120, 130, 140, 150, 145]


def test_fully_synced_requires_streams_for_all_activities(conn: sqlite3.Connection) -> None:
    state = SyncState(conn)
    state.ensure()
    repo = ActivitiesRepository(conn)

    # One enriched activity (with streams), one bare summary (no streams).
    repo.insert_summary({"id": 900003, "start_date": "2021-05-30T08:00:00Z"})
    ActivitiesSyncer(FakeStravaClient(_handler), repo).enrich(900003)
    repo.insert_summary({"id": 900004, "start_date": "2021-05-29T08:00:00Z"})

    state.mark_backfill_complete()
    # Not fully synced: activity 900004 has no streams row.
    assert state.is_fully_synced() is False

    # Give 900004 a streams row → now every activity carries streams.
    StreamsRepository(conn).write(900004, {"time": {"data": [0]}})
    conn.commit()
    assert state.is_fully_synced() is True


def test_not_fully_synced_until_backfill_complete(conn: sqlite3.Connection) -> None:
    state = SyncState(conn)
    state.ensure()
    # No activities at all, but backfill not complete → not fully synced.
    assert state.is_fully_synced() is False
