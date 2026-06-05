"""Gear repository: bikes and shoes (ids sourced from the athlete profile)."""

from __future__ import annotations

import json
from typing import Any

from strava_mcp.db.repositories import (
    BaseRepository,
    dual_write,
    now_iso,
    transaction,
)


class GearRepository(BaseRepository):
    def save(self, gear: dict[str, Any], *, gear_type: str) -> None:
        """Dual-write one gear item (``gear_type`` = ``'bike'`` | ``'shoe'``)."""
        gear_id = str(gear["id"])
        with transaction(self.conn):
            dual_write(
                self.conn,
                resource_type="gear",
                resource_id=gear_id,
                endpoint=f"/gear/{gear_id}",
                payload=gear,
                table="gear",
                values={
                    "id": gear_id,
                    "name": gear.get("name"),
                    "type": gear_type,
                    "detail_json": json.dumps(gear, separators=(",", ":")),
                    "fetched_at": now_iso(),
                },
            )

    def list_all(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT detail_json FROM gear ORDER BY id").fetchall()
        return [json.loads(r["detail_json"]) for r in rows]

    def get(self, gear_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT detail_json FROM gear WHERE id = ?", (gear_id,)).fetchone()
        return None if row is None else json.loads(row["detail_json"])
