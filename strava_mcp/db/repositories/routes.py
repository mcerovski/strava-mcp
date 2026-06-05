"""Routes repository: metadata + polyline map only (no GPX/TCX, PRD §3)."""

from __future__ import annotations

import json
from typing import Any

from strava_mcp.db.repositories import (
    BaseRepository,
    dual_write,
    now_iso,
    transaction,
)


class RoutesRepository(BaseRepository):
    def save(self, route: dict[str, Any]) -> None:
        """Dual-write one route (metadata + polyline)."""
        route_id = str(route.get("id_str") or route["id"])
        with transaction(self.conn):
            dual_write(
                self.conn,
                resource_type="route",
                resource_id=route_id,
                endpoint=f"/routes/{route_id}",
                payload=route,
                table="routes",
                values={
                    "id": route_id,
                    "name": route.get("name"),
                    "type": route.get("type"),
                    "distance": route.get("distance"),
                    "detail_json": json.dumps(route, separators=(",", ":")),
                    "fetched_at": now_iso(),
                },
            )

    def list_all(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT detail_json FROM routes ORDER BY id").fetchall()
        return [json.loads(r["detail_json"]) for r in rows]

    def get(self, route_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT detail_json FROM routes WHERE id = ?", (route_id,)
        ).fetchone()
        return None if row is None else json.loads(row["detail_json"])
