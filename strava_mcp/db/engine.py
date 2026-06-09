"""SQLite connection factory: WAL mode, schema bootstrap, read-only helper.

The worker thread holds one read/write connection (the single writer); each MCP
tool call opens its own read-only connection. WAL lets readers proceed while the
worker writes, with no contention (research R12, Constitution IV).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _schema_sql() -> str:
    return _SCHEMA_PATH.read_text(encoding="utf-8")


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")


def apply_schema(conn: sqlite3.Connection) -> None:
    """Apply (idempotent) the full DDL. Safe to call on every open."""
    conn.executescript(_schema_sql())
    conn.commit()


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open (creating if needed) the read/write DB with WAL + schema applied."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Autocommit mode: we manage transactions explicitly via repositories.transaction
    # (the dual-write unit), so disable the driver's implicit BEGIN.
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    # Bring a legacy database in line with the current schema before applying it
    # (idempotent no-op on fresh/already-migrated databases).
    from strava_mcp.db import migrations

    migrations.migrate(conn)
    apply_schema(conn)
    return conn


def read_only_connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a read-only connection for MCP tools.

    Uses SQLite URI ``mode=ro`` so a tool can never accidentally write. The DB
    must already exist (the worker/serve path creates it).
    """
    path = Path(db_path)
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
