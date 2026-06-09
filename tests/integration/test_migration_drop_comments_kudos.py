"""T018/T027 [US3] Upgrade migration: drop comments/kudos served structures.

Seeds a database in the *legacy* shape (comments/kudos tables + count columns on
``activities``) without triggering the migration, then opens it via
``engine.connect()`` and asserts the migration's postconditions, idempotency,
data/raw-archive preservation, and resume-after-upgrade behavior (FR-010/011/012/015).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from strava_mcp.db import engine


def _seed_legacy(path: Path) -> None:
    """Create a DB in the pre-003 shape, bypassing the migration."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    # Apply the current (new) schema, then re-introduce the legacy structures so
    # the on-disk shape matches an old build's database.
    engine.apply_schema(conn)
    conn.execute("ALTER TABLE activities ADD COLUMN kudos_count INTEGER")
    conn.execute("ALTER TABLE activities ADD COLUMN comment_count INTEGER")
    conn.executescript(
        """
        CREATE TABLE comments (
          id INTEGER PRIMARY KEY, activity_id INTEGER REFERENCES activities(id),
          created_at TEXT, detail_json TEXT NOT NULL
        );
        CREATE INDEX idx_comments_activity ON comments(activity_id);
        CREATE TABLE kudos (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          activity_id INTEGER REFERENCES activities(id),
          athlete_name TEXT, detail_json TEXT NOT NULL
        );
        CREATE INDEX idx_kudos_activity ON kudos(activity_id);
        """
    )
    # One enriched activity + a kept facet (laps) + raw archive rows.
    conn.execute(
        "INSERT INTO activities (id, name, sport_type, start_date_epoch, enriched_at, "
        "detail_json, fetched_at, kudos_count, comment_count) "
        "VALUES (1, 'Ride', 'Ride', 100, 'stamp', '{\"id\":1}', 'stamp', 7, 3)"
    )
    conn.execute(
        "INSERT INTO laps (id, activity_id, lap_index, detail_json) VALUES (10, 1, 0, '{}')"
    )
    conn.execute(
        "INSERT INTO comments (id, activity_id, created_at, detail_json) VALUES (100, 1, 't', '{}')"
    )
    conn.execute(
        "INSERT INTO kudos (activity_id, athlete_name, detail_json) VALUES (1, 'A B', '{}')"
    )
    conn.execute(
        "INSERT INTO raw_responses (resource_type, resource_id, endpoint, fetched_at, payload) "
        "VALUES ('comments', '1', '/activities/1/comments', 't', '[]'),"
        "       ('kudos', '1', '/activities/1/kudos', 't', '[]'),"
        "       ('activity_detail', '1', '/activities/1', 't', '{}')"
    )
    conn.commit()
    conn.close()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    # Exclude SQLite-internal tables (e.g. sqlite_sequence); compare only our schema.
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_migration_drops_served_structures(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    _seed_legacy(path)
    raw_before = (
        sqlite3.connect(str(path)).execute("SELECT COUNT(*) FROM raw_responses").fetchone()[0]
    )

    conn = engine.connect(path)
    try:
        tables = _table_names(conn)
        # 1-2. served structures gone.
        assert "comments" not in tables and "kudos" not in tables
        assert not ({"kudos_count", "comment_count"} & _columns(conn, "activities"))
        # 3. kept data intact.
        assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM laps").fetchone()[0] == 1
        # 4. visibility preserved.
        assert (
            conn.execute("SELECT enriched_at FROM activities WHERE id=1").fetchone()[0] == "stamp"
        )
        # 5. raw archive preserved (including legacy comments/kudos rows).
        assert conn.execute("SELECT COUNT(*) FROM raw_responses").fetchone()[0] == raw_before
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM raw_responses WHERE resource_type IN ('comments','kudos')"
            ).fetchone()[0]
            == 2
        )
        # 6. no FK violations.
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        # activities indexes were recreated.
        idx = {r[1] for r in conn.execute("PRAGMA index_list(activities)")}
        assert "idx_activities_enriched_at" in idx
    finally:
        conn.close()


def test_migration_is_idempotent_and_matches_fresh(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    _seed_legacy(legacy)
    engine.connect(legacy).close()
    # Second open must be a clean no-op.
    conn = engine.connect(legacy)
    fresh = engine.connect(tmp_path / "fresh.db")
    try:
        # 7. upgraded structure == fresh structure.
        assert _table_names(conn) == _table_names(fresh)
        assert _columns(conn, "activities") == _columns(fresh, "activities")
    finally:
        conn.close()
        fresh.close()


def test_fresh_database_is_a_no_op(tmp_path: Path) -> None:
    conn = engine.connect(tmp_path / "new.db")
    try:
        tables = _table_names(conn)
        assert "comments" not in tables and "kudos" not in tables
        assert not ({"kudos_count", "comment_count"} & _columns(conn, "activities"))
    finally:
        conn.close()


def test_resume_after_upgrade_preserves_sync_state(tmp_path: Path) -> None:
    """FR-012: a mid-backfill prior-build DB resumes without losing the frontier."""
    path = tmp_path / "midsync.db"
    _seed_legacy(path)
    seed = sqlite3.connect(str(path), isolation_level=None)
    seed.execute(
        "INSERT INTO sync_state "
        "(id, phase, backfill_frontier_epoch, backfill_complete, updated_at) "
        "VALUES (1, 'BACKFILL', 100, 0, 't')"
    )
    seed.commit()
    seed.close()

    conn = engine.connect(path)
    try:
        row = conn.execute(
            "SELECT phase, backfill_frontier_epoch, backfill_complete FROM sync_state WHERE id=1"
        ).fetchone()
        assert row["phase"] == "BACKFILL"
        assert row["backfill_frontier_epoch"] == 100
        assert row["backfill_complete"] == 0
        # The already-stored activity is intact, so a resume would not re-fetch it.
        assert conn.execute("SELECT COUNT(*) FROM activities WHERE id=1").fetchone()[0] == 1
    finally:
        conn.close()
