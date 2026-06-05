"""Athlete syncer: fetch profile/zones/stats and dual-write via the repository.

Part of the BOOTSTRAP phase (data-model.md). Pure fetch + persist; the worker
orchestrator owns sequencing and the rate budget.
"""

from __future__ import annotations

from typing import Any, Protocol

from strava_mcp.db.repositories.athlete import AthleteRepository


class _Client(Protocol):
    def get(self, path: str, *, params: dict[str, Any] | None = ...) -> Any: ...


class AthleteSyncer:
    def __init__(self, client: _Client, repo: AthleteRepository) -> None:
        self.client = client
        self.repo = repo

    def run(self) -> int:
        """Fetch and persist the athlete; return the athlete id."""
        detail = self.client.get("/athlete")
        athlete_id = int(detail["id"])
        zones = self._safe_get("/athlete/zones")
        stats = self._safe_get(f"/athletes/{athlete_id}/stats")
        self.repo.save(detail=detail, zones=zones, stats=stats)
        return athlete_id

    def _safe_get(self, path: str) -> Any | None:
        """Best-effort fetch — a missing optional facet must not abort BOOTSTRAP."""
        try:
            return self.client.get(path)
        except Exception:
            return None
