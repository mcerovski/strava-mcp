# strava-mcp — Implementation Plan (vertical slices)

Tracer-bullet breakdown of [PRD.md](./PRD.md). Each slice cuts through every layer
(config → DB → Strava client → sync → MCP tool over HTTP) and is demoable on its own.
Vocabulary follows [CONTEXT.md](./CONTEXT.md); rationale in [docs/adr/](./docs/adr/).

**Dependency shape:** `1 → 2 → 3 → { 4 → { 5, 6 }, 7, 8 }`

| # | Slice | Type |
|---|-------|------|
| 1 | Skeleton + `auth` (OAuth → token in DB) | **HITL** |
| 2 | Athlete tracer bullet: `get_athlete` served from DB | AFK |
| 3 | Activity backfill (summaries) + rate limiter + list/get + `sync_status` | AFK |
| 4 | Per-activity enrichment: detail + laps + comments + kudos + zones | AFK |
| 5 | Streams end-to-end: `get_activity_streams` | AFK |
| 6 | Gear, routes, starred segments + their tools | AFK |
| 7 | Steady-state POLL + `sync_now` | AFK |
| 8 | Aggregates + README: `summarize_training` | AFK |

---

## Slice 1 — Skeleton + `auth` (OAuth → token in DB) · HITL

### What to build
The minimal `uv` project plus the `auth` command that completes the full-scope OAuth
authorization-code flow and persists tokens. `auth` builds the authorize URL from
`STRAVA_SCOPES`, opens the browser (falls back to printing the URL when headless), runs a
local callback server on `127.0.0.1:${OAUTH_REDIRECT_PORT}` to auto-capture the `code`,
exchanges it for tokens, writes them to the DB, and verifies the scope actually works by
calling `GET /athlete/activities?per_page=1`. This is the only human-in-the-loop step.
Folds in the just-enough skeleton: `uv` project (`pyproject.toml`), config loader (`.env`),
SQLite engine (WAL), and a `tokens` table.

### Acceptance criteria
- [ ] `uv run strava-mcp auth` opens the browser to Strava's authorize page for the full scopes.
- [ ] The local callback captures `code` automatically (no copy-paste) and exchanges it for tokens.
- [ ] Access + refresh token, `expires_at`, and granted scope are persisted in the DB.
- [ ] The flow verifies success with `GET /athlete/activities?per_page=1` (HTTP 200) and reports the granted scopes.
- [ ] DB-stored tokens take precedence over the `.env` seed on subsequent reads.
- [ ] Config and DB path are read from `.env`; nothing secret is written outside `.database/`.

### Blocked by
None — can start immediately.

---

## Slice 2 — Athlete tracer bullet: `get_athlete` served from DB · AFK

### What to build
The end-to-end pipeline proven on a single resource. `serve` boots, checks the stored token
scope and **exits with instructions** if insufficient, otherwise starts the FastMCP
`streamable-http` server bound to `127.0.0.1` and a background worker thread. The worker's
BOOTSTRAP step fetches the athlete profile, zones, and stats, dual-writes them (raw
`raw_responses` + normalized `athlete` table using lean columns + `detail_json`), and the
`get_athlete` MCP tool returns that data as a pure DB read. Includes a thin Strava HTTP
client (bearer auth, token auto-refresh) — rate limiting can be minimal here (≤3 calls).

### Acceptance criteria
- [ ] `serve` with an insufficient-scope token exits printing `run uv run strava-mcp auth`.
- [ ] `serve` with a valid token starts the HTTP MCP server on loopback and a worker thread.
- [ ] The worker fetches athlete profile + zones + stats and dual-writes (raw + normalized).
- [ ] An MCP client calling `get_athlete` receives the profile/zones/stats from the DB (no live API call by the tool).
- [ ] The HTTP client refreshes the access token via the refresh token when near expiry.
- [ ] SQLite runs in WAL mode; the worker is the only writer.

### Blocked by
Slice 1.

---

## Slice 3 — Activity backfill (summaries) + rate limiter + `list_activities`/`get_activity` + `sync_status` · AFK

### What to build
The core backfill. The worker pages `GET /athlete/activities` newest→oldest, storing each
`SummaryActivity` (raw + normalized `activities` table) and advancing the **backfill
frontier** cursor, checkpointing after every page so it is resumable. This slice carries the
rate limiter: read `X-ReadRateLimit-Usage`/`X-RateLimit-Usage`, and on exhaustion (or `429`)
enter COOLDOWN — sleep until the deterministic next window reset (quarter-hour / midnight
UTC) and resume from the last checkpoint. `list_activities(after?, before?, sport_type?,
limit?)` and `get_activity(id)` serve summaries from the DB; `sync_status()` reports frontier
date, % complete, fully-synced flag, counts, current rate-limit budget, and cooldown ETA.

### Acceptance criteria
- [ ] Backfill pages activities newest→oldest and persists summaries (raw + normalized).
- [ ] The frontier cursor advances and is checkpointed after each page; restarting `serve` resumes from it (no re-fetch).
- [ ] On rate-limit exhaustion/`429` the worker cools down to the known next reset and then resumes automatically.
- [ ] `list_activities` filters by date range / sport_type via promoted columns; `get_activity` returns a stored summary.
- [ ] `sync_status` reports frontier, % complete, counts, rate-limit budget, and cooldown ETA.
- [ ] Progress is logged to stdout and to the rotating file `./.database/strava-mcp.log`.

### Blocked by
Slice 2.

---

## Slice 4 — Per-activity enrichment: detail + laps + comments + kudos + zones · AFK

### What to build
As the frontier reaches each activity, enrich it as one complete unit: `DetailedActivity`,
laps, comments, kudos, and zones — each dual-written into its own lean table (`laps`,
`comments`, `kudos`, `activity_zones`) and the `activities` row upgraded with detail. The
activity's embedded `segment_efforts[]` + `best_efforts[]` populate the `segment_efforts`
table (no standalone effort sweep). An activity becomes visible only once fully enriched.
Tools: `get_activity` now returns full detail; add `get_laps`, `get_comments`, `get_kudos`,
`get_activity_zones`.

### Acceptance criteria
- [ ] Each activity reached by the frontier is enriched with detail + laps + comments + kudos + zones in one pass.
- [ ] An activity row is only marked complete/visible after all enrichment is written (no partial activities).
- [ ] `segment_efforts` is populated from the activity's embedded efforts (no `/segment_efforts` call).
- [ ] `get_activity` returns full `DetailedActivity`; `get_laps`/`get_comments`/`get_kudos`/`get_activity_zones` return their data.
- [ ] Enrichment respects the rate limiter / cooldown from slice 3.

### Blocked by
Slice 3.

---

## Slice 5 — Streams end-to-end: `get_activity_streams` · AFK

### What to build
Extend enrichment to fetch the activity's streams (`time`, `distance`, `latlng`, `altitude`,
`velocity_smooth`, `heartrate`, `cadence`, `watts`, `temp`, `moving`, `grade_smooth`) via
`key_by_type=true`, storing each stream type as a JSON array plus metadata (resolution,
original_size) in `activity_streams`. With streams included, an enriched activity now meets
the "fully synced" definition. Tool: `get_activity_streams(id, keys?)` returns the stored
streams (or "not yet synced" if the frontier hasn't reached it).

### Acceptance criteria
- [ ] Enrichment fetches streams for each activity and stores them per type with metadata.
- [ ] `get_activity_streams` returns the requested stream types from the DB (or "not yet synced").
- [ ] Backfill is considered complete only when the frontier reaches the first activity AND every activity has streams.
- [ ] `sync_status`'s fully-synced flag flips true only after streams are present for all activities.

### Blocked by
Slice 4.

---

## Slice 6 — Gear, routes, starred segments + their tools · AFK

### What to build
Round out the BOOTSTRAP resources. Fetch gear (ids from `athlete.bikes`/`shoes` →
`GET /gear/{id}`), routes (`/athletes/{id}/routes` + `/routes/{id}`, metadata + polyline
only, no GPX/TCX), and starred segments (`/segments/starred` stored as full
`DetailedSegment`). Encountered segments remain the embedded `SummarySegment` from slice 4 —
no per-segment upgrade call. Tools: `list_gear`/`get_gear`, `list_routes`/`get_route`,
`list_starred_segments`/`get_segment`/`list_segment_efforts(segment_id)`.

### Acceptance criteria
- [ ] Gear is fetched for every id referenced by the athlete's bikes/shoes and served by `list_gear`/`get_gear`.
- [ ] Routes are stored as metadata + polyline (no GPX/TCX) and served by `list_routes`/`get_route`.
- [ ] Starred segments are stored as `DetailedSegment`; `get_segment` returns detail for starred and summary for encountered.
- [ ] `list_starred_segments` and `list_segment_efforts(segment_id)` (reading slice-4 efforts) return data.
- [ ] No `/segments/explore` and no per-segment `/segments/{id}` upgrade for encountered segments.

### Blocked by
Slice 4.

---

## Slice 7 — Steady-state POLL + `sync_now` · AFK

### What to build
Once backfill is complete, the worker switches to the steady-state POLL: every 12 hours it
lists `GET /athlete/activities?after = newest_synced − 14 days`, dedupes by activity id, and
enriches + inserts only ids not already stored (catching back-dated uploads without mutating
existing rows), advancing the **newest-synced** cursor. The `sync_now()` tool nudges the poll
to run immediately.

### Acceptance criteria
- [ ] After backfill completes, the worker runs the POLL on a 12-hour cadence.
- [ ] POLL lists with a 14-day lookback and dedupes by activity id; only unseen ids are enriched + inserted.
- [ ] Existing activity rows are never re-fetched or mutated by the POLL.
- [ ] A back-dated upload (start_date within the lookback window) is picked up on the next poll.
- [ ] `sync_now` triggers an immediate POLL run and reports the outcome.

### Blocked by
Slice 3.

---

## Slice 8 — Aggregates + README: `summarize_training` · AFK

### What to build
A DB-side aggregate tool, `summarize_training(period, sport_type?)`, returning cheap rollups
(counts, distance, time, elevation) per period from the promoted columns. Plus a README
documenting setup: `.env`, `uv run strava-mcp auth`, `uv run strava-mcp serve`, and how to
point an MCP client at the loopback HTTP server.

### Acceptance criteria
- [ ] `summarize_training` returns correct rollups for a given period (e.g. weekly/monthly) and optional sport_type, computed in SQL.
- [ ] README covers `.env` config, the `auth` flow, running `serve`, and connecting an MCP client.
- [ ] README states the rate-limit reality (backfill may take days) and the read-only/insert-only scope.

### Blocked by
Slice 3.
