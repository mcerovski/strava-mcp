"""Streams repository: the 1:1 ``activity_streams`` row (R7).

Streams are the dominant data volume, stored per-type as JSON keyed by stream
type (not per-sample rows). The write participates in the caller's enrichment
transaction (no commit of its own) so ``enriched_at`` can be stamped only after
the streams row exists. Read supports key-filtering (US5, T043).
"""

from __future__ import annotations

import json
from typing import Any

from strava_mcp.db.repositories import (
    BaseRepository,
    now_iso,
    record_raw,
    upsert,
)


class StreamsRepository(BaseRepository):
    def write(self, activity_id: int, streams: dict[str, Any]) -> None:
        """Dual-write the activity's streams. Does NOT commit (txn-scoped)."""
        types = ",".join(streams.keys())
        fetched_at = now_iso()
        record_raw(
            self.conn,
            resource_type="streams",
            resource_id=activity_id,
            endpoint=f"/activities/{activity_id}/streams",
            payload=streams,
            fetched_at=fetched_at,
        )
        upsert(
            self.conn,
            "activity_streams",
            {
                "activity_id": activity_id,
                "streams_json": json.dumps(streams, separators=(",", ":")),
                "types": types,
                "fetched_at": fetched_at,
            },
        )

    def read(self, activity_id: int, keys: list[str] | None = None) -> dict[str, Any] | None:
        """Return stored streams (optionally key-filtered) + types metadata."""
        row = self.conn.execute(
            "SELECT streams_json, types FROM activity_streams WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        if row is None:
            return None
        data: dict[str, Any] = json.loads(row["streams_json"])
        if keys:
            wanted = set(keys)
            data = {k: v for k, v in data.items() if k in wanted}
        return {
            "activity_id": activity_id,
            "streams": data,
            "types": list(data.keys()),
        }

    def has_streams(self, activity_id: int) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM activity_streams WHERE activity_id = ?", (activity_id,)
            ).fetchone()
            is not None
        )
