"""T037 [US4] Contract: get_laps/get_comments/get_kudos/get_activity_zones + full get_activity."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from strava_mcp.db.repositories.activities import ActivitiesRepository
from strava_mcp.mcp.tools.activities import (
    get_activity,
    get_activity_zones,
    get_laps,
)
from strava_mcp.sync.resources.activities import ActivitiesSyncer

from tests.conftest import FakeStravaClient
from tests.fixtures import load


def _handler(path: str, params: dict[str, object]) -> object:
    suffix = path.split("/activities/900003")[-1]
    return {
        "": load("activity_detail"),
        "/laps": load("laps"),
        "/zones": load("zones"),
        "/streams": load("streams"),
    }[suffix]


def _enriched(conn: sqlite3.Connection) -> None:
    repo = ActivitiesRepository(conn)
    repo.insert_summary({"id": 900003, "start_date": "2021-05-30T08:00:00Z", "sport_type": "Ride"})
    ActivitiesSyncer(FakeStravaClient(_handler), repo).enrich(900003)


def test_full_get_activity(conn: sqlite3.Connection, db_path: Path) -> None:
    _enriched(conn)
    detail = get_activity(db_path, 900003)
    assert detail["id"] == 900003
    assert "splits_metric" in detail
    assert detail["gear_id"] == "b1234"


def test_facet_tools_return_collections(conn: sqlite3.Connection, db_path: Path) -> None:
    _enriched(conn)
    assert len(get_laps(db_path, 900003)) == 2
    zones = get_activity_zones(db_path, 900003)
    assert {z["type"] for z in zones} == {"heartrate", "power"}


def test_facet_tools_not_yet_synced_when_pending(conn: sqlite3.Connection, db_path: Path) -> None:
    ActivitiesRepository(conn).insert_summary({"id": 55, "start_date": "2021-01-01T00:00:00Z"})
    assert get_laps(db_path, 55) == {"status": "not_yet_synced", "id": 55}
    assert get_activity(db_path, 55) == {"status": "not_yet_synced", "id": 55}


def test_facet_tools_not_found_when_absent(db_path: Path, conn: sqlite3.Connection) -> None:
    assert get_laps(db_path, 12321) == {"status": "not_found", "id": 12321}


def test_removed_comments_kudos_tools_are_unknown_operations(db_path: Path) -> None:
    """FR-014: the removed capabilities are unknown operations, never empty/fabricated."""
    import asyncio

    import pytest
    from fastmcp.exceptions import NotFoundError
    from strava_mcp.mcp import server

    app = server.build_app(db_path)

    async def _run() -> None:
        tools = await app.list_tools()
        names = {t.name for t in tools}
        assert "get_comments" not in names and "get_kudos" not in names
        for removed in ("get_comments", "get_kudos"):
            # FastMCP raises NotFoundError for an unknown tool.
            with pytest.raises(NotFoundError):
                await app.call_tool(removed, {"id": 900003})

    asyncio.run(_run())
