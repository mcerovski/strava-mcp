"""One-shot, idempotent schema migrations applied on DB open (feature 003).

The only migration here removes the served comments/kudos structures from a
database produced by an older build: it drops the ``comments`` and ``kudos``
tables and rebuilds ``activities`` without the ``kudos_count``/``comment_count``
columns, so an upgraded database is structurally identical to a freshly-created
one (FR-011/FR-015). The append-only ``raw_responses`` archive and the
``detail_json`` blobs are preserved untouched.

There is no migration framework: detection is by schema introspection so the
migration is naturally idempotent (a no-op on a fresh or already-migrated DB).
The rebuild uses the portable table-rebuild pattern (not ``ALTER TABLE … DROP
COLUMN``) and runs in a single transaction so an interruption rolls back to the
pre-migration state.
"""

from __future__ import annotations

import sqlite3

_DROP_COLUMNS = ("kudos_count", "comment_count")


def migrate(conn: sqlite3.Connection) -> None:
    """Apply pending migrations. Safe (no-op) when nothing legacy is present."""
    if not _needs_comments_kudos_removal(conn):
        return
    # foreign_keys must be toggled outside any transaction; disable it for the
    # table rebuild and re-validate afterward.
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN")
        conn.execute("DROP TABLE IF EXISTS comments")
        conn.execute("DROP TABLE IF EXISTS kudos")
        _rebuild_without_columns(conn, "activities", _DROP_COLUMNS)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"foreign_key_check failed after migration: {violations}")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return list(conn.execute(f"PRAGMA table_info({table})").fetchall())


def _needs_comments_kudos_removal(conn: sqlite3.Connection) -> bool:
    if _table_exists(conn, "comments") or _table_exists(conn, "kudos"):
        return True
    if not _table_exists(conn, "activities"):
        return False
    names = {row[1] for row in _columns(conn, "activities")}
    return any(col in names for col in _DROP_COLUMNS)


def _col_def(col: sqlite3.Row) -> str:
    """Reconstruct a column definition from a PRAGMA table_info row."""
    _, name, ctype, notnull, default, pk = col
    parts = [name, ctype or "TEXT"]
    if pk:
        parts.append("PRIMARY KEY")
    elif notnull:
        parts.append("NOT NULL")
    if default is not None:
        parts.append(f"DEFAULT {default}")
    return " ".join(parts)


def _rebuild_without_columns(conn: sqlite3.Connection, table: str, drop: tuple[str, ...]) -> None:
    """Rebuild ``table`` dropping ``drop`` columns, preserving rows and indexes."""
    cols = _columns(conn, table)
    if not any(col[1] in drop for col in cols):
        return
    kept = [col for col in cols if col[1] not in drop]
    kept_names = ", ".join(col[1] for col in kept)
    col_defs = ", ".join(_col_def(col) for col in kept)
    # Capture the table's own index DDL; DROP TABLE removes the indexes with it.
    index_ddl = [
        row[0]
        for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
            (table,),
        ).fetchall()
    ]
    conn.execute(f"CREATE TABLE {table}__new ({col_defs})")
    conn.execute(f"INSERT INTO {table}__new ({kept_names}) SELECT {kept_names} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}__new RENAME TO {table}")
    for ddl in index_ddl:
        conn.execute(ddl)
