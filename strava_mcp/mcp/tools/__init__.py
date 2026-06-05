"""MCP read tools — pure SQLite reads (Constitution I, ADR 0001).

Modules in this package MUST NOT import ``strava_mcp.client`` or
``strava_mcp.sync`` (enforced by the pure-reader guard test, T066). They open
their own read-only connection per call so the worker (single writer) is never
blocked under WAL.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def not_yet_synced(activity_id: int | str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "not_yet_synced"}
    if activity_id is not None:
        payload["id"] = activity_id
    return payload


def not_found(resource_id: int | str) -> dict[str, Any]:
    return {"status": "not_found", "id": resource_id}


@contextmanager
def reader(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """Open a read-only connection for the duration of one tool call."""
    from strava_mcp.db import engine

    conn = engine.read_only_connect(db_path)
    try:
        yield conn
    finally:
        conn.close()
