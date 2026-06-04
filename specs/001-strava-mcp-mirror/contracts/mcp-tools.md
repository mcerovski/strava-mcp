# Contract: MCP Tools (agent read surface)

All tools are exposed via FastMCP over `streamable-http` on `127.0.0.1:${MCP_PORT}` and are
**pure SQLite reads — none call Strava** (Constitution I, ADR 0001). Naming follows the
uniform convention: `get_*` returns one resource, `list_*` returns a collection
(Constitution III). Any request for an activity the **frontier** has not yet enriched returns
the documented **`not yet synced`** signal — never a partial or fabricated result.

**Common conventions**
- IDs are Strava numeric ids unless noted (gear/route ids are strings).
- Timestamps in/out are ISO-8601 UTC; `after`/`before` filters accept ISO-8601 or epoch seconds.
- "not yet synced" signal shape: `{ "status": "not_yet_synced", "id": <id> }`.
- Visibility: activity-scoped tools only return data when `activities.enriched_at IS NOT NULL`.
- Errors: unknown id (and not a sync-pending activity) → `{ "status": "not_found", "id": <id> }`.

---

## Athlete

### `get_athlete()`
- **Input**: none.
- **Returns**: `{ profile, zones, stats }` from the `athlete` row (profile = DetailedAthlete,
  zones = `/athlete/zones`, stats = rolled-up `ActivityStats`).
- **Empty state**: if BOOTSTRAP hasn't run yet → `{ "status": "not_yet_synced" }`.
- _Covers_: FR-019; US2.

---

## Activities

### `list_activities(after?, before?, sport_type?, limit?)`
- **Input**: `after` (ISO/epoch, optional), `before` (optional), `sport_type` (optional),
  `limit` (optional, default 30).
- **Filters**: date range on `start_date_epoch`; `sport_type` exact match — both **indexed
  promoted columns**. Only `enriched_at IS NOT NULL` rows returned, newest first.
- **Returns**: array of activity summaries (promoted fields + light `detail_json` excerpt).
- _Covers_: FR-019, FR-020; US3.

### `get_activity(id)`
- **Input**: `id`.
- **Returns**: full `DetailedActivity` (from `detail_json`) incl. splits, best efforts, gear ref.
- **Pending**: summary exists but `enriched_at IS NULL` → `not yet synced`.
- _Covers_: FR-019, FR-020; US3/US4.

### `get_laps(id)` / `get_comments(id)` / `get_kudos(id)` / `get_activity_zones(id)`
- **Input**: activity `id`.
- **Returns**: the respective collection from its lean table (`laps`/`comments`/`kudos`/
  `activity_zones`), each item's `detail_json`.
- **Pending**: activity not yet enriched → `not yet synced`.
- _Covers_: FR-019, FR-020; US4.

### `get_activity_streams(id, keys?)`
- **Input**: activity `id`; `keys?` (optional subset of stream types).
- **Returns**: stored streams for the activity (per-type `{data, series_type, original_size,
  resolution}`); if `keys` given, only those types.
- **Pending**: activity not yet enriched (no `activity_streams` row) → `not yet synced`.
- _Covers_: FR-019, FR-020; US5.

---

## Gear

### `list_gear()`
- **Returns**: all `gear` rows (id, name, type + `detail_json`).

### `get_gear(id)`
- **Input**: gear `id` (string).
- **Returns**: the gear's `detail_json`; unknown → `not_found`.
- _Covers_: FR-019; US6.

---

## Routes

### `list_routes()`
- **Returns**: all `routes` (metadata + polyline map; **no GPX/TCX**).

### `get_route(id)`
- **Input**: route `id` (string).
- **Returns**: route `detail_json` (metadata + polyline); unknown → `not_found`.
- _Covers_: FR-019; US6.

---

## Segments & efforts

### `list_starred_segments()`
- **Returns**: `segments` where `starred = 1` (full `DetailedSegment`).

### `get_segment(id)`
- **Input**: segment `id`.
- **Returns**: `DetailedSegment` if starred, else the embedded `SummarySegment` for an
  encountered segment; unknown → `not_found`. **No live per-segment fetch** (ADR 0001).
- _Covers_: FR-013, FR-019; US6.

### `list_segment_efforts(segment_id)`
- **Input**: `segment_id`.
- **Returns**: the athlete's `segment_efforts` for that segment (indexed by `segment_id`),
  each effort's `detail_json`.
- _Covers_: FR-019; US6.

---

## Sync control & status

### `sync_status()`
- **Returns**: `{ phase, frontier_date, newest_synced_date, percent_complete, fully_synced,
  counts: { activities, enriched, streams, gear, routes, starred_segments },
  rate_limit: { read_15min, read_daily, limits }, cooldown_until }`.
- **Source**: `sync_state` + cheap `COUNT`s. `fully_synced` true only when `backfill_complete`
  AND all activities carry streams (R9).
- _Covers_: FR-021; US3/US5.

### `sync_now()`
- **Effect**: nudges the worker to run the forward **POLL** immediately (no-op/queued if a
  run is already in progress or still in BACKFILL).
- **Returns**: `{ triggered: bool, outcome: <summary of inserted ids or 'no new activities'> }`.
- **Invariant**: never mutates existing rows (insert-only, ADR 0003).
- _Covers_: FR-018; US7.

---

## Aggregates

### `summarize_training(period, sport_type?)`
- **Input**: `period` (e.g. `"weekly"` | `"monthly"`), `sport_type?`.
- **Returns**: per-period rollups `{ period_start, count, distance, moving_time,
  total_elevation_gain }`, **computed in SQL** over promoted columns (Constitution IV), only
  over `enriched_at IS NOT NULL` activities.
- _Covers_: FR-022; US8.

---

## Contract test checklist (Constitution II)

- [ ] Every tool returns stored data or a documented status signal — never partial/fabricated.
- [ ] Activity-scoped tools return `not yet synced` when `enriched_at IS NULL`.
- [ ] No tool module imports `strava_mcp.client` or `strava_mcp.sync` (pure-reader guard test).
- [ ] `list_activities` filters use indexed promoted columns (date range, sport_type).
- [ ] `get_segment` returns detail for starred, summary for encountered, no network call.
- [ ] `summarize_training` rollups match the underlying activities exactly.
- [ ] `sync_status` reports all required fields; `fully_synced` honors the streams condition.
