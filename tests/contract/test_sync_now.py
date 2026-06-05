"""T060 [US7] Contract: sync_now triggers poll, reports outcome, no mutation."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from strava_mcp.mcp.tools.sync import sync_now
from strava_mcp.sync.state import SyncState


def test_sync_now_sets_trigger_and_reports_outcome(conn: sqlite3.Connection, db_path: Path) -> None:
    state = SyncState(conn)
    state.ensure()
    state.append_run_log({"phase": "POLL", "event": "poll", "outcome": "inserted 2 new activities"})

    event = threading.Event()
    result = sync_now(db_path, event)

    assert result["triggered"] is True
    assert event.is_set()  # the worker nudge fired
    assert result["outcome"] == "inserted 2 new activities"


def test_sync_now_without_worker_reports_not_triggered(
    conn: sqlite3.Connection, db_path: Path
) -> None:
    SyncState(conn).ensure()
    result = sync_now(db_path, None)
    assert result["triggered"] is False
    assert result["outcome"] == "no poll has run yet"


def test_sync_now_does_not_mutate_data(conn: sqlite3.Connection, db_path: Path) -> None:
    SyncState(conn).ensure()
    before = conn.execute("SELECT COUNT(*) FROM raw_responses").fetchone()[0]
    sync_now(db_path, threading.Event())
    assert conn.execute("SELECT COUNT(*) FROM raw_responses").fetchone()[0] == before
