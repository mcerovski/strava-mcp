"""Athlete repository: the single ``athlete`` row (detail + zones + stats).

Dual-write: the three source fetches (``/athlete``, ``/athlete/zones``,
``/athletes/{id}/stats``) are each recorded verbatim in ``raw_responses`` and
projected into one normalized ``athlete`` row.
"""

from __future__ import annotations

import json
from typing import Any

from strava_mcp.db.repositories import (
    BaseRepository,
    now_iso,
    record_raw,
    transaction,
    upsert,
)


class AthleteRepository(BaseRepository):
    def save(
        self,
        *,
        detail: dict[str, Any],
        zones: Any | None,
        stats: Any | None,
    ) -> None:
        """Persist the athlete profile/zones/stats (dual-write, atomic)."""
        athlete_id = int(detail["id"])
        fetched_at = now_iso()
        with transaction(self.conn):
            record_raw(
                self.conn,
                resource_type="athlete",
                resource_id=athlete_id,
                endpoint="/athlete",
                payload=detail,
                fetched_at=fetched_at,
            )
            if zones is not None:
                record_raw(
                    self.conn,
                    resource_type="athlete_zones",
                    resource_id=athlete_id,
                    endpoint="/athlete/zones",
                    payload=zones,
                    fetched_at=fetched_at,
                )
            if stats is not None:
                record_raw(
                    self.conn,
                    resource_type="athlete_stats",
                    resource_id=athlete_id,
                    endpoint=f"/athletes/{athlete_id}/stats",
                    payload=stats,
                    fetched_at=fetched_at,
                )
            upsert(
                self.conn,
                "athlete",
                {
                    "id": athlete_id,
                    "username": detail.get("username"),
                    "firstname": detail.get("firstname"),
                    "lastname": detail.get("lastname"),
                    "detail_json": json.dumps(detail, separators=(",", ":")),
                    "zones_json": None
                    if zones is None
                    else json.dumps(zones, separators=(",", ":")),
                    "stats_json": None
                    if stats is None
                    else json.dumps(stats, separators=(",", ":")),
                    "fetched_at": fetched_at,
                },
            )

    def read(self) -> dict[str, Any] | None:
        """Return ``{profile, zones, stats}`` or None if BOOTSTRAP hasn't run."""
        row = self.conn.execute(
            "SELECT detail_json, zones_json, stats_json FROM athlete LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {
            "profile": json.loads(row["detail_json"]),
            "zones": json.loads(row["zones_json"]) if row["zones_json"] else None,
            "stats": json.loads(row["stats_json"]) if row["stats_json"] else None,
        }
