"""Gear read tools: ``list_gear`` and ``get_gear`` (US6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strava_mcp.db.repositories.gear import GearRepository
from strava_mcp.mcp.tools import not_found, reader


def list_gear(db_path: Path | str) -> list[dict[str, Any]]:
    with reader(db_path) as conn:
        return GearRepository(conn).list_all()


def get_gear(db_path: Path | str, gear_id: str) -> dict[str, Any]:
    with reader(db_path) as conn:
        gear = GearRepository(conn).get(gear_id)
    return gear if gear is not None else not_found(gear_id)
