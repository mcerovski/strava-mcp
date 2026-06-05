"""Routes syncer: ``/athletes/{id}/routes`` (list) + ``/routes/{id}`` (detail)."""

from __future__ import annotations

from typing import Any, Protocol

from strava_mcp.db.repositories.routes import RoutesRepository


class _Client(Protocol):
    def get(self, path: str, *, params: dict[str, Any] | None = ...) -> Any: ...


class RoutesSyncer:
    def __init__(self, client: _Client, repo: RoutesRepository) -> None:
        self.client = client
        self.repo = repo

    def run(self, athlete_id: int) -> None:
        listing = self.client.get(f"/athletes/{athlete_id}/routes") or []
        for summary in listing:
            route_id = summary.get("id_str") or summary.get("id")
            detail = self.client.get(f"/routes/{route_id}")
            self.repo.save(detail)
