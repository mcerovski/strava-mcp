"""``summarize_training`` — SQL-computed training rollups (US8).

Aggregates count/distance/moving_time/total_elevation_gain per period over the
indexed promoted columns, computed in SQL (Constitution IV), only across
``enriched_at IS NOT NULL`` activities.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strava_mcp.mcp.tools import reader

# Period → the SQL expression that yields each row's period_start date.
_PERIOD_EXPR = {
    "monthly": "strftime('%Y-%m-01', start_date)",
    # Monday of the activity's ISO week.
    "weekly": (
        "date(start_date, '-' || "
        "((CAST(strftime('%w', start_date) AS INTEGER) + 6) % 7) || ' days')"
    ),
}


def summarize_training(
    db_path: Path | str,
    *,
    period: str = "weekly",
    sport_type: str | None = None,
) -> list[dict[str, Any]]:
    """Per-period rollups (newest period first). ``period`` ∈ {weekly, monthly}."""
    expr = _PERIOD_EXPR.get(period)
    if expr is None:
        raise ValueError(f"unsupported period: {period!r} (use 'weekly' or 'monthly')")

    where = ["enriched_at IS NOT NULL", "start_date IS NOT NULL"]
    params: list[Any] = []
    if sport_type is not None:
        where.append("sport_type = ?")
        params.append(sport_type)

    sql = (
        f"SELECT {expr} AS period_start, "
        "COUNT(*) AS count, "
        "COALESCE(SUM(distance), 0) AS distance, "
        "COALESCE(SUM(moving_time), 0) AS moving_time, "
        "COALESCE(SUM(total_elevation_gain), 0) AS total_elevation_gain "
        "FROM activities "
        f"WHERE {' AND '.join(where)} "
        "GROUP BY period_start ORDER BY period_start DESC"
    )
    with reader(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "period_start": r["period_start"],
            "count": r["count"],
            "distance": r["distance"],
            "moving_time": r["moving_time"],
            "total_elevation_gain": r["total_elevation_gain"],
        }
        for r in rows
    ]
