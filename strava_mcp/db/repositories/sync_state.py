"""Read-only access to the singleton ``sync_state`` row.

The worker owns the *writer* (``strava_mcp.sync.state.SyncState``). This
repository is the read side that pure-reader surfaces (MCP tools, dashboard)
use without importing the sync package — keeping all ``sync_state`` SQL in the
repositories layer.
"""

from __future__ import annotations

from typing import Any

from strava_mcp.db.repositories import BaseRepository

# Defaults for a mirror whose worker has not yet written the singleton row.
_EMPTY_STATE: dict[str, Any] = {"phase": "BOOTSTRAP", "backfill_complete": 0}


class SyncStateRepository(BaseRepository):
    def snapshot(self) -> dict[str, Any]:
        """Return the ``sync_state`` row as a plain dict (empty defaults if absent)."""
        row = self.conn.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
        return dict(row) if row is not None else dict(_EMPTY_STATE)
