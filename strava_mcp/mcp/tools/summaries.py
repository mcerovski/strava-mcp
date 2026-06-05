"""``summarize_training`` — SQL-computed training rollups (US8).

Aggregates count/distance/moving_time/total_elevation_gain per period over the
indexed promoted columns, computed in SQL (Constitution IV), only across
``enriched_at IS NOT NULL`` activities.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strava_mcp.db.repositories.activities import ActivitiesRepository
from strava_mcp.mcp.tools import reader

# Periods this tool exposes. The underlying rollup also supports 'yearly', but the
# tool contract is intentionally unchanged (weekly/monthly only).
_TOOL_PERIODS = ("weekly", "monthly")


def summarize_training(
    db_path: Path | str,
    *,
    period: str = "weekly",
    sport_type: str | None = None,
) -> list[dict[str, Any]]:
    """Per-period rollups (newest period first). ``period`` ∈ {weekly, monthly}.

    Delegates the SQL aggregation to ``ActivitiesRepository.training_rollup`` so the
    grouping logic lives in one place (shared with the dashboard timeline). The tool
    contract is unchanged: only weekly/monthly are accepted here.
    """
    if period not in _TOOL_PERIODS:
        raise ValueError(f"unsupported period: {period!r} (use 'weekly' or 'monthly')")
    with reader(db_path) as conn:
        return ActivitiesRepository(conn).training_rollup(period=period, sport_type=sport_type)
