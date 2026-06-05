"""Gear syncer: bike/shoe ids from the athlete profile → ``/gear/{id}``."""

from __future__ import annotations

from typing import Any, Protocol

from strava_mcp.db.repositories.gear import GearRepository


class _Client(Protocol):
    def get(self, path: str, *, params: dict[str, Any] | None = ...) -> Any: ...


class GearSyncer:
    def __init__(self, client: _Client, repo: GearRepository) -> None:
        self.client = client
        self.repo = repo

    def run(self, athlete_detail: dict[str, Any]) -> None:
        for bike in athlete_detail.get("bikes") or []:
            self._fetch(bike.get("id"), "bike")
        for shoe in athlete_detail.get("shoes") or []:
            self._fetch(shoe.get("id"), "shoe")

    def _fetch(self, gear_id: str | None, gear_type: str) -> None:
        if not gear_id:
            return
        gear = self.client.get(f"/gear/{gear_id}")
        self.repo.save(gear, gear_type=gear_type)
