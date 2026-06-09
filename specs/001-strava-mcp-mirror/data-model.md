# Phase 1 Data Model: Strava MCP Local Mirror

> **Note (superseded in part by feature 003-remove-comments-kudos):** the
> `comments` and `kudos` tables and the `kudos_count`/`comment_count` columns on
> `activities` were removed. The live schema is `strava_mcp/db/schema.sql`; this
> historical data model is otherwise unchanged.

SQLite schema realizing the entities in [spec.md](./spec.md) under the design decisions in
[research.md](./research.md) and ADRs 0001–0003. **Pattern (ADR 0002):** every normalized
table carries keys + lean **promoted columns** (indexed, the only fields agents filter/sort/
aggregate on) + a `detail_json` blob for everything else. Every fetched resource is also
written verbatim to `raw_responses` (**dual-write**, Constitution I). WAL mode, single writer.

Conventions: epoch columns are integer Unix seconds (UTC); `*_json` columns hold JSON text;
ISO timestamps are TEXT. Promoted columns are chosen to back the tool filters in
[contracts/mcp-tools.md](./contracts/mcp-tools.md) — adding any beyond these requires a query
need (Constitution I, YAGNI).

## Entity overview & relationships

```text
athlete (1 row) ──< gear
                └─< routes
                └─< segments (starred)
activities (central) ──1:1── activity_streams
                      ├──< laps
                      ├──< comments
                      ├──< kudos
                      ├──< activity_zones
                      └──< segment_efforts >── segments (encountered = embedded summary)
tokens (1 row)            sync_state (1 row)        raw_responses (append-only, all resources)
```

---

## Raw store (backup, append-only) — ADR 0002

```text
raw_responses(
  id           INTEGER PRIMARY KEY,
  resource_type TEXT NOT NULL,   -- 'athlete','athlete_zones','athlete_stats','activity',
                                 --   'activity_detail','laps','comments','kudos','zones',
                                 --   'streams','gear','route','segment', ...
  resource_id  TEXT,             -- Strava id as string (gear/route ids are non-numeric)
  endpoint     TEXT NOT NULL,    -- request path that produced it
  fetched_at   TEXT NOT NULL,    -- ISO-8601 UTC
  payload      TEXT NOT NULL     -- verbatim API JSON body
)
-- INDEX raw_responses(resource_type, resource_id)
```

Append-only: never updated or deleted. The normalized tables are a rebuildable projection of
this store.

---

## Normalized tables

### `tokens` (single row) — R4

```text
tokens(
  id            INTEGER PRIMARY KEY CHECK (id = 1),
  access_token  TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  expires_at    INTEGER NOT NULL,   -- epoch seconds
  scope         TEXT NOT NULL,      -- comma-separated granted scopes
  updated_at    TEXT NOT NULL
)
```
- Written by `auth` and by the worker's refresh. DB row overrides `.env` seed once present.
- Validation: `scope` must contain all required read scopes for `serve` to start (R6).

### `athlete` (single row)

```text
athlete(
  id           INTEGER PRIMARY KEY,   -- Strava athlete id
  username     TEXT,
  firstname    TEXT,
  lastname     TEXT,
  detail_json  TEXT NOT NULL,         -- full DetailedAthlete
  zones_json   TEXT,                  -- /athlete/zones
  stats_json   TEXT,                  -- /athletes/{id}/stats
  fetched_at   TEXT NOT NULL
)
```
- Sources: `GET /athlete`, `/athlete/zones`, `/athletes/{id}/stats` (BOOTSTRAP).

### `activities` (central) — R8

```text
activities(
  id                    INTEGER PRIMARY KEY,   -- Strava activity id
  -- promoted (indexed) — the queryable fields:
  start_date            TEXT,                  -- ISO-8601 UTC
  start_date_epoch      INTEGER,               -- for range filters & cursor math
  start_date_local      TEXT,
  sport_type            TEXT,
  name                  TEXT,
  distance              REAL,
  moving_time           INTEGER,
  elapsed_time          INTEGER,
  total_elevation_gain  REAL,
  average_heartrate     REAL,
  max_heartrate         REAL,
  average_watts         REAL,
  max_watts             REAL,
  average_speed         REAL,
  kudos_count           INTEGER,
  comment_count         INTEGER,
  gear_id               TEXT,
  trainer               INTEGER,               -- 0/1
  commute               INTEGER,               -- 0/1
  private               INTEGER,               -- 0/1
  -- lifecycle:
  enriched_at           TEXT,                  -- NULL until fully enriched (visibility flag)
  detail_json           TEXT NOT NULL,         -- SummaryActivity, upgraded to DetailedActivity
  fetched_at            TEXT NOT NULL
)
-- INDEX activities(start_date_epoch)
-- INDEX activities(sport_type)
-- INDEX activities(enriched_at)
```
- **Visibility rule (R8, Constitution III):** read tools return an activity only when
  `enriched_at IS NOT NULL`. Summary row may exist earlier (during paging) but is invisible.
- **Single-unit enrichment:** detail + laps + comments + kudos + zones + streams +
  segment_efforts written in one transaction; `enriched_at` stamped last.

### `activity_streams` (1:1 with activity) — R7

```text
activity_streams(
  activity_id   INTEGER PRIMARY KEY REFERENCES activities(id),
  streams_json  TEXT NOT NULL,   -- { "<type>": {data, series_type, original_size, resolution}, ... }
  types         TEXT,            -- comma-separated stream types present (convenience)
  fetched_at    TEXT NOT NULL
)
```
- Source: `GET /activities/{id}/streams?keys=...&key_by_type=true`. One row per activity
  (atomic write within enrichment). Per-type JSON, not per-sample rows (Constitution IV).

### `laps`

```text
laps(
  id            INTEGER PRIMARY KEY,   -- Strava lap id
  activity_id   INTEGER REFERENCES activities(id),
  lap_index     INTEGER,
  detail_json   TEXT NOT NULL
)
-- INDEX laps(activity_id)
```

### `comments`

```text
comments(
  id            INTEGER PRIMARY KEY,   -- Strava comment id
  activity_id   INTEGER REFERENCES activities(id),
  created_at    TEXT,
  detail_json   TEXT NOT NULL
)
-- INDEX comments(activity_id)
```

### `kudos`

```text
kudos(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,  -- kudos have no stable id; synthesize
  activity_id   INTEGER REFERENCES activities(id),
  athlete_name  TEXT,                  -- "firstname lastname" (promoted convenience)
  detail_json   TEXT NOT NULL          -- SummaryAthlete of the kudoer
)
-- INDEX kudos(activity_id)
```

### `activity_zones`

```text
activity_zones(
  activity_id   INTEGER REFERENCES activities(id),
  zone_type     TEXT,                  -- 'heartrate' | 'power'
  detail_json   TEXT NOT NULL,         -- distribution buckets
  PRIMARY KEY (activity_id, zone_type)
)
```

### `segment_efforts` — populated from embedded activity data (ADR 0001, no standalone sweep)

```text
segment_efforts(
  id             INTEGER PRIMARY KEY,   -- Strava segment_effort id
  segment_id     INTEGER,               -- the segment attempted
  activity_id    INTEGER REFERENCES activities(id),
  start_date     TEXT,
  start_date_epoch INTEGER,
  elapsed_time   INTEGER,
  moving_time    INTEGER,
  detail_json    TEXT NOT NULL          -- full effort (rank, PR, achievements, ...)
)
-- INDEX segment_efforts(segment_id)
-- INDEX segment_efforts(activity_id)
```
- Source: `segment_efforts[]` + `best_efforts[]` embedded in `DetailedActivity` (enrichment).

### `segments`

```text
segments(
  id            INTEGER PRIMARY KEY,   -- Strava segment id
  name          TEXT,
  starred       INTEGER NOT NULL,      -- 1 = DetailedSegment from /segments/starred; 0 = encountered summary
  detail_json   TEXT NOT NULL          -- DetailedSegment (starred) or SummarySegment (encountered)
)
-- INDEX segments(starred)
```
- **Starred** (`/segments/starred`) stored as full `DetailedSegment`. **Encountered** stored as
  the `SummarySegment` embedded in efforts — **no per-segment upgrade call** (ADR 0001, PRD §3).
- On conflict: a starred fetch upgrades an existing encountered row; an encountered insert never
  downgrades a starred row.

### `gear`

```text
gear(
  id            TEXT PRIMARY KEY,      -- non-numeric Strava gear id ("b1234"/"g5678")
  name          TEXT,
  type          TEXT,                  -- 'bike' | 'shoe'
  detail_json   TEXT NOT NULL,
  fetched_at    TEXT NOT NULL
)
```
- Ids sourced from `athlete.bikes`/`athlete.shoes` → `GET /gear/{id}`.

### `routes`

```text
routes(
  id            TEXT PRIMARY KEY,      -- route id (string-safe)
  name          TEXT,
  type          INTEGER,               -- ride/run
  distance      REAL,
  detail_json   TEXT NOT NULL,         -- metadata + polyline map; NO GPX/TCX (PRD §3)
  fetched_at    TEXT NOT NULL
)
```
- Sources: `/athletes/{id}/routes` (list) + `/routes/{id}` (detail). Metadata + polyline only.

### `sync_state` (single row) — R9

```text
sync_state(
  id                     INTEGER PRIMARY KEY CHECK (id = 1),
  phase                  TEXT NOT NULL,      -- 'BOOTSTRAP'|'BACKFILL'|'COOLDOWN'|'POLL'
  backfill_frontier_epoch INTEGER,          -- oldest enriched start_date (moves older)
  newest_synced_epoch     INTEGER,          -- newest enriched start_date (moves newer)
  backfill_complete       INTEGER NOT NULL DEFAULT 0,
  last_poll_at            TEXT,
  cooldown_until          TEXT,             -- ISO-8601 when COOLDOWN ends (else NULL)
  rate_limit_json         TEXT,             -- latest {read:{15min,daily,limit}, overall:{...}}
  run_log_json            TEXT,             -- recent run history entries
  updated_at              TEXT NOT NULL
)
```
- Backs `sync_status`. Checkpointed after every backfill page (resume w/o re-fetch, Constitution IV).
- **Fully synced** = `backfill_complete = 1` AND every activity has `enriched_at` set incl. streams.

---

## State transitions

### Worker phases (sync_state.phase) — ADR 0001
```text
BOOTSTRAP  -> athlete profile/zones/stats, gear, routes, starred segments  (once)
   ↓
BACKFILL   -> page /athlete/activities newest→oldest; enrich each as a unit;
              advance frontier; checkpoint after every page
   ├─ budget exhausted / 429 ─→ COOLDOWN (sleep to known next reset) ─→ BACKFILL
   └─ reached first-ever activity & all enriched incl. streams ─→ backfill_complete=1
   ↓
POLL       -> every 12h: list after=newest_synced−14d; dedupe-by-id;
              enrich+insert unseen only; advance newest_synced (never mutate)
   └─ sync_now() nudges an immediate POLL
```

### Activity lifecycle (R8)
```text
(absent) → summary inserted (enriched_at NULL, invisible)
         → enrichment txn writes all facets + streams, stamps enriched_at (visible)
POLL path: unseen id → summary+enrichment in one go → visible; seen id → skipped (insert-only)
```

## Validation & invariants (testable — Constitution II)

- **Dual-write**: any normalized insert has a corresponding `raw_responses` row for that fetch.
- **Visibility**: no tool returns an activity with `enriched_at IS NULL`; such reads → `not yet synced`.
- **Insert-only**: POLL never UPDATEs/DELETEs an existing `activities` row; only inserts unseen ids.
- **Lookback/dedupe**: a back-dated upload within 14 days of `newest_synced` is caught; dedupe by id.
- **Resume**: restart mid-BACKFILL re-fetches zero already-enriched activities (frontier checkpoint).
- **Fully synced flag** flips true only after streams exist for all activities and frontier reached first-ever.
- **Starred precedence**: starred segment row is never downgraded to a summary by an encountered insert.
