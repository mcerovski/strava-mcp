"""Base repository helpers and the dual-write primitive (Constitution I).

Every normalized write is paired with a verbatim ``raw_responses`` row for the
same fetch. ``dual_write`` performs both in one call; callers control the
transaction boundary so a single-unit enrichment can write many resources
atomically (data-model.md, single-unit enrichment).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any


def now_iso() -> str:
    """Current instant as ISO-8601 UTC (seconds-resolution, ``Z`` suffix)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dumps(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def record_raw(
    conn: sqlite3.Connection,
    *,
    resource_type: str,
    resource_id: str | int | None,
    endpoint: str,
    payload: Any,
    fetched_at: str | None = None,
) -> str:
    """Append one verbatim row to the raw store. Returns the ``fetched_at`` used."""
    stamp = fetched_at or now_iso()
    conn.execute(
        "INSERT INTO raw_responses "
        "(resource_type, resource_id, endpoint, fetched_at, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            resource_type,
            None if resource_id is None else str(resource_id),
            endpoint,
            stamp,
            _dumps(payload),
        ),
    )
    return stamp


def upsert(
    conn: sqlite3.Connection,
    table: str,
    values: Mapping[str, Any],
    *,
    replace: bool = True,
) -> None:
    """INSERT OR REPLACE / OR IGNORE a normalized row from a column->value map."""
    cols = list(values)
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    sql = f"{verb} INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
    conn.execute(sql, tuple(values[c] for c in cols))


def dual_write(
    conn: sqlite3.Connection,
    *,
    resource_type: str,
    resource_id: str | int | None,
    endpoint: str,
    payload: Any,
    table: str,
    values: Mapping[str, Any],
    replace: bool = True,
    fetched_at: str | None = None,
) -> str:
    """The dual-write primitive: raw row + normalized row in one call.

    Does not commit — the caller owns the transaction so multiple dual-writes
    can be grouped into a single atomic unit.
    """
    stamp = record_raw(
        conn,
        resource_type=resource_type,
        resource_id=resource_id,
        endpoint=endpoint,
        payload=payload,
        fetched_at=fetched_at,
    )
    upsert(conn, table, values, replace=replace)
    return stamp


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Atomic unit: commit on success, roll back on any exception."""
    try:
        conn.execute("BEGIN")
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


class BaseRepository:
    """Common base holding a read/write connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
