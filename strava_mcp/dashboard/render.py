"""HTML rendering for the dashboard (server-side, escaped, no client JS).

Every dynamic value is passed through ``html.escape``. The only stylesheet is the
locally-served ``/static/app.css``; there are no external/CDN references.
"""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlencode

from strava_mcp.dashboard import views

_NAV = (("/", "Activities"), ("/timeline", "Timeline"), ("/sync", "Sync"))


def _e(value: Any) -> str:
    return escape("" if value is None else str(value))


def page(title: str, body: str, *, active: str, athlete: dict[str, Any] | None) -> str:
    """Wrap body content in the shared HTML shell (topbar + nav + athlete header)."""
    nav = "".join(
        f'<a href="{_e(href)}" class="{"active" if href == active else ""}">{_e(label)}</a>'
        for href, label in _NAV
    )
    header = views.athlete_header(athlete)
    athlete_html = (
        f'<div class="athlete">Athlete: <strong>{_e(header["name"])}</strong></div>'
        if header
        else '<div class="athlete">No athlete synced yet</div>'
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)} · strava-mcp</title>"
        '<link rel="stylesheet" href="/static/app.css"></head><body>'
        '<header class="topbar"><span class="brand">strava-mcp</span>'
        f"<nav>{nav}</nav>{athlete_html}</header>"
        f"<main>{body}</main></body></html>"
    )


def _query(**params: Any) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "", 0)}
    return ("?" + urlencode(clean)) if clean else ""


# --- activity list (US1) ---------------------------------------------------
def list_page(
    *,
    result: dict[str, Any],
    sport_type: str | None,
    after: str | None,
    before: str | None,
    sports: list[str],
    athlete: dict[str, Any] | None,
) -> str:
    options = '<option value="">All sports</option>' + "".join(
        f'<option value="{_e(s)}"{" selected" if s == sport_type else ""}>{_e(s)}</option>'
        for s in sports
    )
    filters = (
        '<form class="filters" method="get" action="/">'
        f'<label>Sport<select name="sport_type">{options}</select></label>'
        f'<label>After<input type="date" name="after" value="{_e(after)}"></label>'
        f'<label>Before<input type="date" name="before" value="{_e(before)}"></label>'
        '<button type="submit">Filter</button>'
        "</form>"
    )

    items = result["items"]
    if not items:
        body = filters + (
            '<div class="empty">No activities match. Once the backfill has enriched '
            "activities, they will appear here.</div>"
        )
        return page("Activities", body, active="/", athlete=athlete)

    rows = "".join(
        "<tr>"
        f"<td>{_e(it['date'])}</td>"
        f'<td><a href="/activity/{_e(it["id"])}">{_e(it["name"])}</a></td>'
        f"<td>{_e(it['sport_type'])}</td>"
        f'<td class="num">{_e(it["distance"])}</td>'
        f'<td class="num">{_e(it["moving_time"])}</td>'
        f'<td class="num">{_e(it["elevation"])}</td>'
        f'<td class="num">{_e(it["heartrate"])}</td>'
        f'<td class="num">{_e(it["watts"])}</td>'
        "</tr>"
        for it in (views.list_item(r) for r in items)
    )
    table = (
        "<table><thead><tr><th>Date</th><th>Activity</th><th>Sport</th>"
        '<th class="num">Distance</th><th class="num">Moving</th>'
        '<th class="num">Elev</th><th class="num">Avg HR</th>'
        '<th class="num">Avg W</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )

    page_no, pages = result["page"], result["pages"]

    def _page_link(target: int) -> str:
        return "/" + _query(sport_type=sport_type, after=after, before=before, page=target)

    prev_link = (
        f'<a href="{_page_link(page_no - 1)}">‹ Prev</a>'
        if page_no > 1
        else '<span class="muted">‹ Prev</span>'
    )
    next_link = (
        f'<a href="{_page_link(page_no + 1)}">Next ›</a>'
        if page_no < pages
        else '<span class="muted">Next ›</span>'
    )
    pager = (
        f'<div class="pager">{prev_link}'
        f'<span class="muted">Page {page_no} of {pages}</span>{next_link}</div>'
    )
    count = f'<p class="count">{_e(result["total"])} activities</p>'
    return page("Activities", filters + count + table + pager, active="/", athlete=athlete)


# --- activity detail (US2) -------------------------------------------------
def detail_page(*, data: dict[str, Any], charts: list[str], athlete: dict[str, Any] | None) -> str:
    detail = data["detail"]
    name = detail.get("name") or "(unnamed)"
    sport = _e(detail.get("sport_type") or "")
    when = _e(views.fmt_date(detail.get("start_date_local") or detail.get("start_date")))
    meta = f"{sport} · {when}"
    cards = "".join(
        f'<div class="card"><div class="k">{_e(c["k"])}</div>'
        f'<div class="v">{_e(c["v"])}</div></div>'
        for c in views.detail_summary(detail)
    )
    body = [
        '<p><a href="/">‹ All activities</a></p>',
        f'<h1>{_e(name)}</h1><p class="count">{meta}</p>',
        f'<div class="cards">{cards}</div>',
    ]

    # Graphs
    body.append("<h2>Streams</h2>")
    if charts:
        body.extend(charts)
    else:
        body.append('<p class="note">No stream data for this activity.</p>')

    # Laps
    laps = views.lap_rows(data["laps"])
    if laps:
        rows = "".join(
            "<tr>"
            f"<td>{_e(lap['name'])}</td>"
            f'<td class="num">{_e(lap["distance"])}</td>'
            f'<td class="num">{_e(lap["moving_time"])}</td>'
            f'<td class="num">{_e(lap["elevation"])}</td>'
            f'<td class="num">{_e(lap["heartrate"])}</td>'
            "</tr>"
            for lap in laps
        )
        body.append(
            "<h2>Laps</h2><table><thead><tr><th>Lap</th>"
            '<th class="num">Distance</th><th class="num">Moving</th>'
            '<th class="num">Elev</th><th class="num">Avg HR</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )

    # Segment efforts
    efforts = views.effort_rows(data["segment_efforts"])
    if efforts:
        rows = "".join(
            "<tr>"
            f"<td>{_e(ef['name'])}</td>"
            f'<td class="num">{_e(ef["distance"])}</td>'
            f'<td class="num">{_e(ef["elapsed_time"])}</td>'
            "</tr>"
            for ef in efforts
        )
        body.append(
            "<h2>Segment efforts</h2><table><thead><tr><th>Segment</th>"
            '<th class="num">Distance</th><th class="num">Time</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )

    # Zone distribution
    blocks = views.zone_blocks(data["zones"])
    if blocks:
        body.append("<h2>Zone distribution</h2>")
        for block in blocks:
            rows = "".join(
                "<tr>"
                f"<td>{_e(z['label'])}</td>"
                f'<td class="num">{_e(z["time"])}</td>'
                f'<td><div class="bar"><span style="width:{_e(z["pct"])}%"></span></div></td>'
                f'<td class="num">{_e(z["pct"])}%</td>'
                "</tr>"
                for z in block["rows"]
            )
            body.append(f"<h3>{_e(block['type'])}</h3><table><tbody>{rows}</tbody></table>")

    return page(name, "".join(body), active="/", athlete=athlete)


def not_found_page(*, message: str, athlete: dict[str, Any] | None) -> str:
    body = f'<div class="empty">{_e(message)}</div><p><a href="/">‹ All activities</a></p>'
    return page("Not found", body, active="/", athlete=athlete)


# --- timeline (US3) --------------------------------------------------------
def timeline_page(
    *,
    buckets: list[dict[str, Any]],
    period: str,
    sport_type: str | None,
    sports: list[str],
    athlete: dict[str, Any] | None,
) -> str:
    period_opts = "".join(
        f'<option value="{p}"{" selected" if p == period else ""}>{label}</option>'
        for p, label in (("week", "Weekly"), ("month", "Monthly"), ("year", "Yearly"))
    )
    sport_opts = '<option value="">All sports</option>' + "".join(
        f'<option value="{_e(s)}"{" selected" if s == sport_type else ""}>{_e(s)}</option>'
        for s in sports
    )
    filters = (
        '<form class="filters" method="get" action="/timeline">'
        f'<label>Period<select name="period">{period_opts}</select></label>'
        f'<label>Sport<select name="sport_type">{sport_opts}</select></label>'
        '<button type="submit">Apply</button></form>'
    )
    if not buckets:
        body = filters + '<div class="empty">No activities to summarize yet.</div>'
        return page("Timeline", body, active="/timeline", athlete=athlete)

    rows = "".join(
        "<tr>"
        f"<td>{_e(r['period_start'])}</td>"
        f'<td class="num">{_e(r["count"])}</td>'
        f'<td class="num">{_e(r["distance"])}</td>'
        f'<td class="num">{_e(r["moving_time"])}</td>'
        f'<td class="num">{_e(r["elevation"])}</td>'
        f'<td><div class="bar"><span style="width:{_e(r["bar_pct"])}%"></span></div></td>'
        "</tr>"
        for r in views.timeline_rows(buckets)
    )
    table = (
        '<table><thead><tr><th>Period</th><th class="num">Activities</th>'
        '<th class="num">Distance</th><th class="num">Moving</th>'
        '<th class="num">Elev</th><th>Volume</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )
    return page("Timeline", filters + table, active="/timeline", athlete=athlete)


# --- sync progress (US4) ---------------------------------------------------
def sync_page(*, progress: dict[str, Any], athlete: dict[str, Any] | None) -> str:
    counts = progress["counts"]
    phase = progress.get("phase") or "—"
    synced_badge = (
        '<span class="badge ok">fully synced</span>'
        if progress.get("fully_synced")
        else f'<span class="badge">{_e(phase)}</span>'
    )
    frontier = progress.get("frontier_date")
    cards = [
        ("Phase", phase),
        ("Backfill", f"{progress.get('percent_complete')}%"),
        ("Frontier", views.fmt_date(frontier) if frontier else "—"),
        ("Activities", counts["activities"]),
        ("Enriched", counts["enriched"]),
        ("Streams", counts["streams"]),
    ]
    cards_html = "".join(
        f'<div class="card"><div class="k">{_e(k)}</div><div class="v">{_e(v)}</div></div>'
        for k, v in cards
    )

    rate = progress.get("rate_limit")
    rate_html = (
        f"<p>Rate-limit usage: {_e(rate)}</p>"
        if rate
        else '<p class="note">No rate-limit data yet.</p>'
    )
    cooldown = progress.get("cooldown_until")
    cooldown_html = (
        f"<p>Cooldown until: <strong>{_e(cooldown)}</strong></p>"
        if cooldown
        else '<p class="note">No active cooldown.</p>'
    )
    last_poll = progress.get("last_poll_at")
    poll_html = f"<p>Last poll: {_e(last_poll)}</p>" if last_poll else ""

    body = (
        f"<h1>Sync progress {synced_badge}</h1>"
        f'<div class="cards">{cards_html}</div>'
        f"{rate_html}{cooldown_html}{poll_html}"
        '<p class="note">Reload the page to see the latest progress.</p>'
    )
    return page("Sync", body, active="/sync", athlete=athlete)
