"""Route handlers: parse the request, read via queries, render HTML.

Each handler returns ``(status_code, html)``. No SQL or Strava access here — the
data comes from ``queries`` (which composes the repositories layer).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strava_mcp.dashboard import charts, queries, render
from strava_mcp.db.repositories.activities import parse_epoch

# UI period token -> repository rollup period.
_PERIOD_MAP = {"week": "weekly", "month": "monthly", "year": "yearly"}


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def handle_list(db_path: Path | str, params: dict[str, list[str]]) -> tuple[int, str]:
    sport_type = _first(params, "sport_type")
    after = _first(params, "after")
    before = _first(params, "before")
    page = _int(_first(params, "page"), 1)

    result = queries.list_activities_page(
        db_path,
        after_epoch=parse_epoch(after) if after else None,
        before_epoch=parse_epoch(before) if before else None,
        sport_type=sport_type,
        page=page,
    )
    athlete = queries.athlete_header(db_path)
    sports = queries.sport_types(db_path)
    html = render.list_page(
        result=result,
        sport_type=sport_type,
        after=after,
        before=before,
        sports=sports,
        athlete=athlete,
    )
    return 200, html


def handle_detail(db_path: Path | str, activity_id: int) -> tuple[int, str]:
    athlete = queries.athlete_header(db_path)
    data = queries.activity_detail(db_path, activity_id)
    if data is None:
        html = render.not_found_page(
            message=(
                f"Activity {activity_id} is not available — it does not exist or is "
                "not yet synced (only fully-enriched activities are shown)."
            ),
            athlete=athlete,
        )
        return 404, html
    svgs = charts.build_activity_charts(data["streams"])
    html = render.detail_page(data=data, charts=svgs, athlete=athlete)
    return 200, html


def handle_timeline(db_path: Path | str, params: dict[str, list[str]]) -> tuple[int, str]:
    ui_period = (_first(params, "period") or "month").lower()
    period = _PERIOD_MAP.get(ui_period, "monthly")
    sport_type = _first(params, "sport_type")

    buckets = queries.timeline(db_path, period=period, sport_type=sport_type)
    athlete = queries.athlete_header(db_path)
    sports = queries.sport_types(db_path)
    html = render.timeline_page(
        buckets=buckets,
        period=ui_period if ui_period in _PERIOD_MAP else "month",
        sport_type=sport_type,
        sports=sports,
        athlete=athlete,
    )
    return 200, html


def handle_sync(db_path: Path | str) -> tuple[int, str]:
    progress = queries.sync_progress(db_path)
    athlete = queries.athlete_header(db_path)
    html = render.sync_page(progress=progress, athlete=athlete)
    return 200, html


def handle_not_found(db_path: Path | str, _path: str) -> tuple[int, str]:
    athlete: dict[str, Any] | None = None
    try:
        athlete = queries.athlete_header(db_path)
    except Exception:
        athlete = None
    return 404, render.not_found_page(message="Page not found.", athlete=athlete)
