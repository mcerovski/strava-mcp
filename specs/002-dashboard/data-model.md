# Phase 1 Data Model: Local Data Dashboard

The dashboard adds **no tables and no columns** — it is a pure reader over the existing mirror
(`activities`, `activity_streams`, `laps`, `activity_zones`, `segment_efforts`, `athlete`,
`sync_state`; see `strava_mcp/db/schema.sql`). What follows are the **read-projection view models**
the dashboard composes from those tables for rendering. They are derived on read; nothing is persisted.

All activity-bearing views obey the existing **visibility invariant**: only rows with
`enriched_at IS NOT NULL` are ever included (reuses `ActivitiesRepository` visibility-aware reads).

---

## ActivityListItem

One row in the activity list.

| Field | Source | Notes |
|-------|--------|-------|
| `id` | `activities.id` | links to the detail view |
| `start_date_local` | promoted column | displayed date (athlete-local) |
| `sport_type` | promoted column | also the filter key |
| `name` | promoted column | escaped on render |
| `distance` | promoted column | formatted (km/mi by simple unit choice) |
| `moving_time` | promoted column | formatted h:mm:ss |
| `total_elevation_gain` | promoted column | formatted |
| `average_heartrate` | promoted column | shown when present |
| `average_watts` | promoted column | shown when present |

**Query**: `ActivitiesRepository.list_page(after_epoch, before_epoch, sport_type, limit, offset)` +
`count_enriched(filters)` for the pager. Ordered `start_date_epoch DESC`.

**Filters**: `sport_type` (exact, indexed), date range (`start_date_epoch >=/<=`, indexed).

**Pagination**: `limit` (default 50) + `offset`; total count drives the page links (FR-015).

---

## ActivityDetailView

The per-activity deep dive (FR-007/008/008a).

| Section | Source | Empty/degraded behavior |
|---------|--------|--------------------------|
| Summary metrics | `activities.detail_json` via `get_detail(id)` | `not_found` state if id absent/not enriched |
| Laps | `laps` via `laps(id)` | omit section if none |
| Segment efforts | `segment_efforts` via `efforts_for_activity(id)` | omit section if none |
| Zone distribution | `activity_zones` via `zones(id)` | omit section if none |
| Stream graphs | `activity_streams` via `StreamsRepository.read(id)` | "no stream data" note if row absent |

**Social data (kudos/comments) is intentionally excluded** for v1 (clarified).

---

## StreamChart (input to `charts.py`)

A single rendered graph for one present stream type.

| Field | Source | Notes |
|-------|--------|-------|
| `type` | stream key (`heartrate`, `watts`, `velocity_smooth`, `altitude`, `cadence`, …) | only present types produce a chart |
| `x` | `time` or `distance` stream | x-axis basis |
| `y` | the stream's sample series | downsampled to ≈800–1200 points before SVG |
| `unit`/`label` | derived from type | axis labelling |

Absent stream types produce **no** chart (never a faked/empty graph) — FR-008/008a.

---

## TimelineBucket

One week/month/year bucket in the timeline (FR-009/010, US3).

| Field | Source | Notes |
|-------|--------|-------|
| `period_start` | `strftime(...)` group key | week = Monday; month = 1st; year = Jan 1 |
| `count` | `COUNT(*)` | enriched activities in the bucket |
| `distance` | `SUM(distance)` | SQL aggregate |
| `moving_time` | `SUM(moving_time)` | SQL aggregate |
| `total_elevation_gain` | `SUM(total_elevation_gain)` | SQL aggregate |

**Query**: `ActivitiesRepository.training_rollup(period ∈ {weekly,monthly,yearly}, sport_type)`. Buckets
with no activities are **filled as zero buckets in Python** between the min and max returned period, so
training gaps stay visible (US3 scenario 3). All sums computed in SQL (Constitution IV).

---

## AthleteHeader

Small identity/context header (FR-018).

| Field | Source | Notes |
|-------|--------|-------|
| `firstname`/`lastname`/`username` | `athlete` row via `AthleteRepository.read()` | escaped |
| high-level totals | `athlete.stats_json` | optional; degrade gracefully if absent |

Renders a neutral placeholder if no athlete row exists yet (empty mirror).

---

## SyncProgressView

The sync-progress page (FR-011/012, US4). Computed exactly like the `sync_status` MCP tool, at request
time, with **no auto-refresh**.

| Field | Source | Notes |
|-------|--------|-------|
| `phase` | `sync_state.phase` | BOOTSTRAP / BACKFILL / POLL (vocabulary) |
| `frontier_date` | `backfill_frontier_epoch` | ISO; oldest reached |
| `percent_complete` | enriched/activities (or 100 if backfill complete) | estimate |
| `counts` | COUNTs (activities, enriched, streams, gear, routes, starred) | cheap reads |
| `fully_synced` | `backfill_complete AND streams >= activities` | DB truth |
| `rate_limit` | `sync_state.rate_limit_json` | current budget |
| `cooldown_until` | `sync_state.cooldown_until` | ETA when in cooldown |
| `last_poll_at` | `sync_state.last_poll_at` | shown when fully synced/polling |

Shows the last persisted state if the worker is not running (the figures simply do not advance).

---

## Relationships (existing, unchanged)

```
athlete (1) ── (the single mirrored account)
activities (1) ──< laps
activities (1) ──< segment_efforts >── segments
activities (1) ──< activity_zones
activities (1) ── (1) activity_streams
sync_state (1 row) ── progress/observability
```

No foreign keys, indexes, or columns are added by this feature.
