"""T074 Multiple MCP clients connect and the server persists across sessions.

Closes FR-007. The FastMCP app is reconstructable per session over the same DB,
and multiple independent read-only connections (standing in for concurrent
clients) read consistent data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from strava_mcp.db.repositories.athlete import AthleteRepository
from strava_mcp.mcp import server
from strava_mcp.mcp.tools.athlete import get_athlete

from tests.fixtures import load


def _seed_athlete(conn: sqlite3.Connection) -> None:
    AthleteRepository(conn).save(
        detail=load("athlete"), zones=load("athlete_zones"), stats=load("athlete_stats")
    )


def test_app_is_reconstructable_per_session(conn: sqlite3.Connection, db_path: Path) -> None:
    _seed_athlete(conn)
    # Two independent server sessions over the same DB build successfully.
    app1 = server.build_app(db_path)
    app2 = server.build_app(db_path)
    assert app1 is not app2
    assert app1.name == "strava-mcp"


def test_multiple_clients_read_consistent_data(conn: sqlite3.Connection, db_path: Path) -> None:
    _seed_athlete(conn)
    # Several concurrent read-only "clients" each open their own connection.
    results = [get_athlete(db_path) for _ in range(5)]
    assert all(r["profile"]["id"] == 12345 for r in results)


def test_registered_tool_set(db_path: Path) -> None:
    import asyncio
    import inspect

    app = server.build_app(db_path)
    tools = app.list_tools()
    if inspect.iscoroutine(tools):
        tools = asyncio.run(tools)
    names = {t.name for t in tools}
    expected = {
        "get_athlete",
        "list_activities",
        "get_activity",
        "get_laps",
        "get_comments",
        "get_kudos",
        "get_activity_zones",
        "get_activity_streams",
        "list_gear",
        "get_gear",
        "list_routes",
        "get_route",
        "list_starred_segments",
        "get_segment",
        "list_segment_efforts",
        "summarize_training",
        "sync_status",
        "sync_now",
    }
    assert expected <= names
