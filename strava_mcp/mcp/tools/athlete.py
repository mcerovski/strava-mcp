"""``get_athlete`` — pure DB read of the single athlete row (US2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strava_mcp.db.repositories.athlete import AthleteRepository
from strava_mcp.mcp.tools import not_yet_synced, reader


def get_athlete(db_path: Path | str) -> dict[str, Any]:
    """Return ``{profile, zones, stats}`` from the DB, or ``not_yet_synced``."""
    with reader(db_path) as conn:
        result = AthleteRepository(conn).read()
    if result is None:
        return not_yet_synced()
    return result
