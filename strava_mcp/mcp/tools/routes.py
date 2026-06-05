"""Route read tools: ``list_routes`` and ``get_route`` (US6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strava_mcp.db.repositories.routes import RoutesRepository
from strava_mcp.mcp.tools import not_found, reader


def list_routes(db_path: Path | str) -> list[dict[str, Any]]:
    with reader(db_path) as conn:
        return RoutesRepository(conn).list_all()


def get_route(db_path: Path | str, route_id: str) -> dict[str, Any]:
    with reader(db_path) as conn:
        route = RoutesRepository(conn).get(str(route_id))
    return route if route is not None else not_found(route_id)
