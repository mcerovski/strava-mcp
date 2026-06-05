"""Activities repository: summary inserts, visibility-aware reads, filters.

Promoted columns (indexed) back the tool filters; everything else lives in
``detail_json`` (ADR 0002). Reads are **visibility-aware**: only rows with
``enriched_at IS NOT NULL`` are returned (R8, Constitution III). Enrichment
writers (laps/comments/kudos/zones/efforts) are added in US4 (T038).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from strava_mcp.db.repositories import (
    BaseRepository,
    now_iso,
    record_raw,
    transaction,
    upsert,
)

# Promoted columns copied out of the activity JSON (besides id/lifecycle).
_PROMOTED_KEYS = (
    "start_date",
    "start_date_local",
    "name",
    "distance",
    "moving_time",
    "elapsed_time",
    "total_elevation_gain",
    "average_heartrate",
    "max_heartrate",
    "average_watts",
    "max_watts",
    "average_speed",
    "kudos_count",
    "comment_count",
    "gear_id",
)


def parse_epoch(start_date: str | None) -> int | None:
    """Parse an ISO-8601 UTC timestamp into epoch seconds."""
    if not start_date:
        return None
    text = start_date.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


def _bool_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def promote(activity: dict[str, Any]) -> dict[str, Any]:
    """Build the promoted-column map from a summary or detailed activity."""
    cols: dict[str, Any] = {key: activity.get(key) for key in _PROMOTED_KEYS}
    cols["start_date_epoch"] = parse_epoch(activity.get("start_date"))
    cols["sport_type"] = activity.get("sport_type") or activity.get("type")
    cols["trainer"] = _bool_int(activity.get("trainer"))
    cols["commute"] = _bool_int(activity.get("commute"))
    cols["private"] = _bool_int(activity.get("private"))
    return cols


class ActivitiesRepository(BaseRepository):
    # --- write (backfill paging) ------------------------------------------
    def insert_summary(self, summary: dict[str, Any]) -> None:
        """Insert a summary row (invisible: ``enriched_at`` NULL), insert-only.

        Uses INSERT OR IGNORE so an already-enriched row is never clobbered by a
        later summary page (insert-only, ADR 0003).
        """
        activity_id = int(summary["id"])
        fetched_at = now_iso()
        with transaction(self.conn):
            record_raw(
                self.conn,
                resource_type="activity",
                resource_id=activity_id,
                endpoint="/athlete/activities",
                payload=summary,
                fetched_at=fetched_at,
            )
            values = {
                "id": activity_id,
                **promote(summary),
                "enriched_at": None,
                "detail_json": json.dumps(summary, separators=(",", ":")),
                "fetched_at": fetched_at,
            }
            upsert(self.conn, "activities", values, replace=False)

    # --- read (visibility-aware) ------------------------------------------
    def status(self, activity_id: int) -> str:
        """Return ``'enriched'`` | ``'pending'`` | ``'absent'`` for an id."""
        row = self.conn.execute(
            "SELECT enriched_at FROM activities WHERE id = ?", (activity_id,)
        ).fetchone()
        if row is None:
            return "absent"
        return "enriched" if row["enriched_at"] is not None else "pending"

    def get_detail(self, activity_id: int) -> dict[str, Any] | None:
        """Full ``DetailedActivity`` if enriched, else None."""
        row = self.conn.execute(
            "SELECT detail_json FROM activities WHERE id = ? AND enriched_at IS NOT NULL",
            (activity_id,),
        ).fetchone()
        if row is None:
            return None
        detail: dict[str, Any] = json.loads(row["detail_json"])
        return detail

    def list_activities(
        self,
        *,
        after_epoch: int | None = None,
        before_epoch: int | None = None,
        sport_type: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Enriched activities (newest first) matching the indexed filters."""
        clauses = ["enriched_at IS NOT NULL"]
        params: list[Any] = []
        if after_epoch is not None:
            clauses.append("start_date_epoch >= ?")
            params.append(after_epoch)
        if before_epoch is not None:
            clauses.append("start_date_epoch <= ?")
            params.append(before_epoch)
        if sport_type is not None:
            clauses.append("sport_type = ?")
            params.append(sport_type)
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM activities WHERE {' AND '.join(clauses)} "
            "ORDER BY start_date_epoch DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._summary_view(row) for row in rows]

    @staticmethod
    def _summary_view(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "sport_type": row["sport_type"],
            "start_date": row["start_date"],
            "start_date_local": row["start_date_local"],
            "distance": row["distance"],
            "moving_time": row["moving_time"],
            "elapsed_time": row["elapsed_time"],
            "total_elevation_gain": row["total_elevation_gain"],
            "average_heartrate": row["average_heartrate"],
            "average_watts": row["average_watts"],
            "average_speed": row["average_speed"],
            "kudos_count": row["kudos_count"],
            "comment_count": row["comment_count"],
            "gear_id": row["gear_id"],
        }

    # --- enrichment (single-unit write, US4) ------------------------------
    def enrich(
        self,
        *,
        detail: dict[str, Any],
        laps: list[dict[str, Any]] | None,
        comments: list[dict[str, Any]] | None,
        kudos: list[dict[str, Any]] | None,
        zones: list[dict[str, Any]] | None,
        streams: dict[str, Any] | None,
    ) -> None:
        """Write all facets + streams in one transaction; stamp ``enriched_at`` last.

        The visibility invariant (R8) requires streams: an enrichment without a
        streams payload must never stamp ``enriched_at``. So a missing streams
        payload raises and the activity stays ``not_yet_synced``.
        """
        if streams is None:
            raise ValueError("enrichment requires streams (visibility invariant)")
        from strava_mcp.db.repositories.streams import StreamsRepository

        activity_id = int(detail["id"])
        stamp = now_iso()
        with transaction(self.conn):
            record_raw(
                self.conn,
                resource_type="activity_detail",
                resource_id=activity_id,
                endpoint=f"/activities/{activity_id}",
                payload=detail,
                fetched_at=stamp,
            )
            # Upgrade summary → detail; enriched_at intentionally left NULL here.
            upsert(
                self.conn,
                "activities",
                {
                    "id": activity_id,
                    **promote(detail),
                    "enriched_at": None,
                    "detail_json": json.dumps(detail, separators=(",", ":")),
                    "fetched_at": stamp,
                },
            )
            self._write_laps(activity_id, laps or [])
            self._write_comments(activity_id, comments or [])
            self._write_kudos(activity_id, kudos or [])
            self._write_zones(activity_id, zones or [])
            self._write_efforts(activity_id, detail)
            StreamsRepository(self.conn).write(activity_id, streams)
            # Stamp visibility LAST, only after streams are persisted (R8).
            self.conn.execute(
                "UPDATE activities SET enriched_at = ? WHERE id = ?",
                (stamp, activity_id),
            )

    def _write_laps(self, activity_id: int, laps: list[dict[str, Any]]) -> None:
        record_raw(
            self.conn,
            resource_type="laps",
            resource_id=activity_id,
            endpoint=f"/activities/{activity_id}/laps",
            payload=laps,
        )
        self.conn.execute("DELETE FROM laps WHERE activity_id = ?", (activity_id,))
        for lap in laps:
            upsert(
                self.conn,
                "laps",
                {
                    "id": int(lap["id"]),
                    "activity_id": activity_id,
                    "lap_index": lap.get("lap_index"),
                    "detail_json": json.dumps(lap, separators=(",", ":")),
                },
            )

    def _write_comments(self, activity_id: int, comments: list[dict[str, Any]]) -> None:
        record_raw(
            self.conn,
            resource_type="comments",
            resource_id=activity_id,
            endpoint=f"/activities/{activity_id}/comments",
            payload=comments,
        )
        self.conn.execute("DELETE FROM comments WHERE activity_id = ?", (activity_id,))
        for comment in comments:
            upsert(
                self.conn,
                "comments",
                {
                    "id": int(comment["id"]),
                    "activity_id": activity_id,
                    "created_at": comment.get("created_at"),
                    "detail_json": json.dumps(comment, separators=(",", ":")),
                },
            )

    def _write_kudos(self, activity_id: int, kudoers: list[dict[str, Any]]) -> None:
        record_raw(
            self.conn,
            resource_type="kudos",
            resource_id=activity_id,
            endpoint=f"/activities/{activity_id}/kudos",
            payload=kudoers,
        )
        # Kudos have no stable id; re-derive the set on each enrichment.
        self.conn.execute("DELETE FROM kudos WHERE activity_id = ?", (activity_id,))
        for kudoer in kudoers:
            name = " ".join(p for p in (kudoer.get("firstname"), kudoer.get("lastname")) if p)
            self.conn.execute(
                "INSERT INTO kudos (activity_id, athlete_name, detail_json) VALUES (?, ?, ?)",
                (activity_id, name, json.dumps(kudoer, separators=(",", ":"))),
            )

    def _write_zones(self, activity_id: int, zones: list[dict[str, Any]]) -> None:
        record_raw(
            self.conn,
            resource_type="zones",
            resource_id=activity_id,
            endpoint=f"/activities/{activity_id}/zones",
            payload=zones,
        )
        self.conn.execute("DELETE FROM activity_zones WHERE activity_id = ?", (activity_id,))
        for zone in zones:
            upsert(
                self.conn,
                "activity_zones",
                {
                    "activity_id": activity_id,
                    "zone_type": zone.get("type"),
                    "detail_json": json.dumps(zone, separators=(",", ":")),
                },
            )

    def _write_efforts(self, activity_id: int, detail: dict[str, Any]) -> None:
        """Populate segment_efforts from the embedded effort lists (ADR 0001).

        No separate raw row: efforts are embedded in the ``activity_detail``
        payload already recorded above.
        """
        from strava_mcp.db.repositories.segments import SegmentsRepository

        segments = SegmentsRepository(self.conn)
        self.conn.execute("DELETE FROM segment_efforts WHERE activity_id = ?", (activity_id,))
        embedded = list(detail.get("segment_efforts") or []) + list(
            detail.get("best_efforts") or []
        )
        for effort in embedded:
            segment = effort.get("segment") or {}
            upsert(
                self.conn,
                "segment_efforts",
                {
                    "id": int(effort["id"]),
                    "segment_id": segment.get("id"),
                    "activity_id": activity_id,
                    "start_date": effort.get("start_date"),
                    "start_date_epoch": parse_epoch(effort.get("start_date")),
                    "elapsed_time": effort.get("elapsed_time"),
                    "moving_time": effort.get("moving_time"),
                    "detail_json": json.dumps(effort, separators=(",", ":")),
                },
            )
            # Encountered segment summary (never downgrades a starred row).
            segments.insert_encountered(segment)

    # --- facet reads (visibility-aware, US4) ------------------------------
    def _facet(self, table: str, activity_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            f"SELECT detail_json FROM {table} WHERE activity_id = ?", (activity_id,)
        ).fetchall()
        return [json.loads(r["detail_json"]) for r in rows]

    def laps(self, activity_id: int) -> list[dict[str, Any]]:
        return self._facet("laps", activity_id)

    def comments(self, activity_id: int) -> list[dict[str, Any]]:
        return self._facet("comments", activity_id)

    def kudos(self, activity_id: int) -> list[dict[str, Any]]:
        return self._facet("kudos", activity_id)

    def zones(self, activity_id: int) -> list[dict[str, Any]]:
        return self._facet("activity_zones", activity_id)

    # --- counts / cursors (for sync_status) -------------------------------
    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0])

    def count_enriched(self) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM activities WHERE enriched_at IS NOT NULL"
            ).fetchone()[0]
        )

    def oldest_summary_epoch(self) -> int | None:
        row = self.conn.execute("SELECT MIN(start_date_epoch) AS e FROM activities").fetchone()
        return None if row["e"] is None else int(row["e"])
