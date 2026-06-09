"""Activity read tools: ``list_activities`` and ``get_activity`` (US3/US4).

Pure DB reads over indexed promoted columns. Visibility-aware: only
``enriched_at IS NOT NULL`` rows are returned; a summary that exists but is not
yet enriched yields ``not_yet_synced``; an unknown id yields ``not_found``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strava_mcp.db.repositories.activities import ActivitiesRepository, parse_epoch
from strava_mcp.mcp.tools import not_found, not_yet_synced, reader


def _to_epoch(value: int | float | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(value)
    except ValueError:
        return parse_epoch(value)


def list_activities(
    db_path: Path | str,
    *,
    after: int | str | None = None,
    before: int | str | None = None,
    sport_type: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Enriched activity summaries (newest first) matching the filters."""
    with reader(db_path) as conn:
        return ActivitiesRepository(conn).list_activities(
            after_epoch=_to_epoch(after),
            before_epoch=_to_epoch(before),
            sport_type=sport_type,
            limit=limit,
        )


def get_activity(db_path: Path | str, activity_id: int) -> dict[str, Any]:
    """Full ``DetailedActivity`` if enriched, else a status signal."""
    with reader(db_path) as conn:
        repo = ActivitiesRepository(conn)
        status = repo.status(activity_id)
        if status == "absent":
            return not_found(activity_id)
        if status == "pending":
            return not_yet_synced(activity_id)
        detail = repo.get_detail(activity_id)
    return detail if detail is not None else not_yet_synced(activity_id)


def _facet(db_path: Path | str, activity_id: int, name: str) -> Any:
    """Return an activity's facet collection, or a status signal if not enriched."""
    with reader(db_path) as conn:
        repo = ActivitiesRepository(conn)
        status = repo.status(activity_id)
        if status == "absent":
            return not_found(activity_id)
        if status == "pending":
            return not_yet_synced(activity_id)
        return getattr(repo, name)(activity_id)


def get_laps(db_path: Path | str, activity_id: int) -> Any:
    """The activity's laps, or ``not_yet_synced``/``not_found``."""
    return _facet(db_path, activity_id, "laps")


def get_activity_zones(db_path: Path | str, activity_id: int) -> Any:
    """The activity's heart-rate/power zones, or ``not_yet_synced``/``not_found``."""
    return _facet(db_path, activity_id, "zones")
