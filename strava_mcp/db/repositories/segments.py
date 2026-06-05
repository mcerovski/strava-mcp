"""Segments repository: starred (full detail) vs encountered (embedded summary).

Starred segments come from ``/segments/starred`` as full ``DetailedSegment``.
Encountered segments are the ``SummarySegment`` embedded in segment efforts — no
per-segment upgrade call (ADR 0001). Precedence (data-model): a starred fetch
upgrades an encountered row; an encountered insert never downgrades a starred row.
"""

from __future__ import annotations

import json
from typing import Any

from strava_mcp.db.repositories import (
    BaseRepository,
    record_raw,
    transaction,
    upsert,
)


class SegmentsRepository(BaseRepository):
    def upsert_starred(self, segment: dict[str, Any]) -> None:
        """Store/upgrade a starred segment (full detail). Owns its transaction."""
        with transaction(self.conn):
            self._write_starred(segment)

    def _write_starred(self, segment: dict[str, Any]) -> None:
        segment_id = int(segment["id"])
        record_raw(
            self.conn,
            resource_type="segment",
            resource_id=segment_id,
            endpoint="/segments/starred",
            payload=segment,
        )
        # REPLACE upgrades an existing encountered row to starred.
        upsert(
            self.conn,
            "segments",
            {
                "id": segment_id,
                "name": segment.get("name"),
                "starred": 1,
                "detail_json": json.dumps(segment, separators=(",", ":")),
            },
            replace=True,
        )

    def insert_encountered(self, segment: dict[str, Any]) -> None:
        """Insert an encountered segment summary; never downgrade a starred row.

        No separate raw row: the embedded summary lives in the ``activity_detail``
        payload recorded by enrichment. Uses INSERT OR IGNORE so an existing row
        (starred or encountered) is left intact.
        """
        if not segment or "id" not in segment:
            return
        upsert(
            self.conn,
            "segments",
            {
                "id": int(segment["id"]),
                "name": segment.get("name"),
                "starred": 0,
                "detail_json": json.dumps(segment, separators=(",", ":")),
            },
            replace=False,
        )

    # --- reads -------------------------------------------------------------
    def list_starred(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT detail_json FROM segments WHERE starred = 1 ORDER BY id"
        ).fetchall()
        return [json.loads(r["detail_json"]) for r in rows]

    def get(self, segment_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT detail_json FROM segments WHERE id = ?", (segment_id,)
        ).fetchone()
        return None if row is None else json.loads(row["detail_json"])

    def efforts_for_segment(self, segment_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT detail_json FROM segment_efforts WHERE segment_id = ? "
            "ORDER BY start_date_epoch DESC",
            (segment_id,),
        ).fetchall()
        return [json.loads(r["detail_json"]) for r in rows]

    def efforts_for_activity(self, activity_id: int) -> list[dict[str, Any]]:
        """Segment efforts recorded during one activity (for the dashboard detail view)."""
        rows = self.conn.execute(
            "SELECT detail_json FROM segment_efforts WHERE activity_id = ? "
            "ORDER BY start_date_epoch",
            (activity_id,),
        ).fetchall()
        return [json.loads(r["detail_json"]) for r in rows]
