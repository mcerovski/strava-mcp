"""``get_activity_streams`` — pure DB read of stored streams (US5).

Returns the per-type streams stored by the US4 enrichment unit, optionally
filtered to requested keys. An activity not yet fully enriched (no streams row)
yields ``not_yet_synced``; an unknown id yields ``not_found``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strava_mcp.db.repositories.activities import ActivitiesRepository
from strava_mcp.db.repositories.streams import StreamsRepository
from strava_mcp.mcp.tools import not_found, not_yet_synced, reader


def get_activity_streams(
    db_path: Path | str, activity_id: int, keys: list[str] | None = None
) -> dict[str, Any]:
    """Return stored streams (optionally key-filtered), or a status signal."""
    with reader(db_path) as conn:
        status = ActivitiesRepository(conn).status(activity_id)
        if status == "absent":
            return not_found(activity_id)
        if status == "pending":
            return not_yet_synced(activity_id)
        result = StreamsRepository(conn).read(activity_id, keys)
    if result is None:
        return not_yet_synced(activity_id)
    return result
