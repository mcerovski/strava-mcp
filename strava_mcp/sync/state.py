"""Access to the single ``sync_state`` row (research R9).

Holds the worker phase, backfill frontier / newest-synced cursors, the
``backfill_complete`` flag, cooldown, the latest rate-limit snapshot, and a
short run log. Checkpointed after every backfill page so a restart resumes with
zero re-fetch (Constitution IV). Extended across US2 (phase) → US3 (cursors,
cooldown, run log) → US5 (fully-synced).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from strava_mcp.db.repositories import now_iso

_MAX_RUN_LOG = 20

VALID_PHASES = {"BOOTSTRAP", "BACKFILL", "COOLDOWN", "POLL"}


class SyncState:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def ensure(self) -> None:
        """Create the singleton row (phase BOOTSTRAP) if it does not exist."""
        existing = self.conn.execute("SELECT 1 FROM sync_state WHERE id = 1").fetchone()
        if existing is None:
            self.conn.execute(
                "INSERT INTO sync_state (id, phase, backfill_complete, updated_at) "
                "VALUES (1, 'BOOTSTRAP', 0, ?)",
                (now_iso(),),
            )
            self.conn.commit()

    def _update(self, **fields: Any) -> None:
        fields["updated_at"] = now_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE sync_state SET {cols} WHERE id = 1", tuple(fields.values()))
        self.conn.commit()

    def snapshot(self) -> dict[str, Any]:
        """Return the current row as a plain dict (empty defaults if absent)."""
        row = self.conn.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
        if row is None:
            return {"phase": "BOOTSTRAP", "backfill_complete": 0}
        return dict(row)

    # --- phase -------------------------------------------------------------
    def set_phase(self, phase: str) -> None:
        if phase not in VALID_PHASES:
            raise ValueError(f"unknown sync phase: {phase}")
        self._update(phase=phase)

    @property
    def phase(self) -> str:
        return str(self.snapshot().get("phase", "BOOTSTRAP"))

    # --- cursors -----------------------------------------------------------
    def set_frontier(self, epoch: int) -> None:
        self._update(backfill_frontier_epoch=epoch)

    def set_newest_synced(self, epoch: int) -> None:
        self._update(newest_synced_epoch=epoch)

    def mark_backfill_complete(self) -> None:
        self._update(backfill_complete=1)

    def is_fully_synced(self) -> bool:
        """True iff backfill is complete AND every activity carries streams (R9).

        Drives the worker's BACKFILL→POLL transition (US7). The ``sync_status``
        tool computes the same condition independently from DB truth so it never
        has to import the worker (pure-reader boundary).
        """
        if not self.snapshot().get("backfill_complete"):
            return False
        row = self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM activities) AS a, "
            "(SELECT COUNT(*) FROM activity_streams) AS s"
        ).fetchone()
        return int(row["s"]) >= int(row["a"])

    # --- cooldown / rate limit / run log -----------------------------------
    def set_cooldown(self, until_iso: str | None) -> None:
        self._update(cooldown_until=until_iso)

    def set_rate_limit(self, snapshot: dict[str, Any]) -> None:
        self._update(rate_limit_json=json.dumps(snapshot, separators=(",", ":")))

    def set_last_poll(self, at_iso: str) -> None:
        self._update(last_poll_at=at_iso)

    def append_run_log(self, entry: dict[str, Any]) -> None:
        snap = self.snapshot()
        log: list[dict[str, Any]] = json.loads(snap.get("run_log_json") or "[]")
        log.append({"at": now_iso(), **entry})
        log = log[-_MAX_RUN_LOG:]
        self._update(run_log_json=json.dumps(log, separators=(",", ":")))
