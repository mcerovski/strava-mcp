"""View-model builders: shape raw repository dicts into display-ready values.

Formatting (distances, durations, dates) lives here; HTML/escaping lives in
``render.py``. These functions never touch the database.
"""

from __future__ import annotations

from typing import Any


# --- formatting helpers ----------------------------------------------------
def fmt_distance(meters: float | int | None) -> str:
    if not meters:
        return "—"
    return f"{meters / 1000:.1f} km"


def fmt_duration(seconds: float | int | None) -> str:
    if not seconds:
        return "—"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def fmt_elevation(meters: float | int | None) -> str:
    if meters is None:
        return "—"
    return f"{meters:.0f} m"


def fmt_int(value: float | int | None, unit: str = "") -> str:
    if value is None:
        return "—"
    suffix = f" {unit}" if unit else ""
    return f"{value:.0f}{suffix}"


def fmt_date(iso: str | None) -> str:
    """Render an ISO timestamp as YYYY-MM-DD (date portion only)."""
    if not iso:
        return "—"
    return iso[:10]


# --- list (US1) ------------------------------------------------------------
def list_item(row: dict[str, Any]) -> dict[str, Any]:
    """Display-ready row for the activity list."""
    return {
        "id": row["id"],
        "date": fmt_date(row.get("start_date_local") or row.get("start_date")),
        "sport_type": row.get("sport_type") or "—",
        "name": row.get("name") or "(unnamed)",
        "distance": fmt_distance(row.get("distance")),
        "moving_time": fmt_duration(row.get("moving_time")),
        "elevation": fmt_elevation(row.get("total_elevation_gain")),
        "heartrate": fmt_int(row.get("average_heartrate"), "bpm"),
        "watts": fmt_int(row.get("average_watts"), "W"),
    }


# --- athlete header (FR-018) ----------------------------------------------
def athlete_header(athlete: dict[str, Any] | None) -> dict[str, Any] | None:
    """Name (+ optional location) for the page header, or None if no athlete row."""
    if not athlete:
        return None
    profile = athlete.get("profile") or {}
    name = " ".join(p for p in (profile.get("firstname"), profile.get("lastname")) if p).strip()
    return {
        "name": name or profile.get("username") or "Athlete",
        "username": profile.get("username"),
    }


# --- detail (US2) ----------------------------------------------------------
def detail_summary(detail: dict[str, Any]) -> list[dict[str, str]]:
    """Summary metric cards for the activity detail header."""
    cards = [
        ("Distance", fmt_distance(detail.get("distance"))),
        ("Moving time", fmt_duration(detail.get("moving_time"))),
        ("Elevation", fmt_elevation(detail.get("total_elevation_gain"))),
        ("Avg HR", fmt_int(detail.get("average_heartrate"), "bpm")),
        ("Avg power", fmt_int(detail.get("average_watts"), "W")),
    ]
    return [{"k": k, "v": v} for k, v in cards]


def lap_rows(laps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for lap in laps:
        rows.append(
            {
                "index": lap.get("lap_index"),
                "name": lap.get("name") or f"Lap {lap.get('lap_index')}",
                "distance": fmt_distance(lap.get("distance")),
                "moving_time": fmt_duration(lap.get("moving_time")),
                "elevation": fmt_elevation(lap.get("total_elevation_gain")),
                "heartrate": fmt_int(lap.get("average_heartrate"), "bpm"),
            }
        )
    return rows


def effort_rows(efforts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for e in efforts:
        segment = e.get("segment") or {}
        rows.append(
            {
                "name": segment.get("name") or e.get("name") or "(segment)",
                "elapsed_time": fmt_duration(e.get("elapsed_time")),
                "distance": fmt_distance(
                    e.get("distance") if e.get("distance") is not None else segment.get("distance")
                ),
            }
        )
    return rows


def zone_blocks(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """HR/power zone distribution: per zone-type, time-in-bucket with percentages."""
    blocks = []
    for z in zones:
        buckets = z.get("distribution_buckets") or []
        total = sum(int(b.get("time") or 0) for b in buckets) or 1
        rows = []
        for i, b in enumerate(buckets, start=1):
            t = int(b.get("time") or 0)
            rows.append(
                {
                    "label": f"Z{i} ({b.get('min')}–{b.get('max')})",
                    "time": fmt_duration(t),
                    "pct": round(t / total * 100),
                }
            )
        blocks.append({"type": z.get("type") or "zone", "rows": rows})
    return blocks


# --- timeline (US3) --------------------------------------------------------
def timeline_rows(buckets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Display-ready timeline rows plus a relative bar width for distance."""
    max_dist = max((b["distance"] for b in buckets), default=0) or 1
    rows = []
    for b in buckets:
        rows.append(
            {
                "period_start": b["period_start"],
                "count": b["count"],
                "distance": fmt_distance(b["distance"]),
                "moving_time": fmt_duration(b["moving_time"]),
                "elevation": fmt_elevation(b["total_elevation_gain"]),
                "bar_pct": round(b["distance"] / max_dist * 100),
            }
        )
    return rows
