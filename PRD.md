# strava-mcp — Product Requirements Document (PRD)

> A locally-run Python MCP server that gives AI agents read access to your full
> Strava history, backed by a local SQLite database that mirrors the Strava API.

Status: **draft / pre-implementation** · Runtime: Python 3.11+ managed by [`uv`](https://docs.astral.sh/uv/) · API: [Strava API v3](https://developers.strava.com/docs/reference/) (OpenAPI vendored under [`strava-api-spec/`](./strava-api-spec/))

---

## 1. Goal

Run a single local process that:

1. Authenticates to Strava once (OAuth 2.0), then keeps tokens fresh automatically.
2. **Syncs** your Strava data into a local SQLite database (`./.database/strava.db`).
3. Serves that data to AI agents over MCP (HTTP transport via FastMCP) so an agent
   can answer questions about your fitness journey without ever touching the live
   API directly.

The database is the source of truth for the agent; Strava is the source of truth
for the database.

## 2. Confirmed decisions

| Decision | Choice | Implication |
|----------|--------|-------------|
| Data fetch | **Eager — one unified backfill** | The background sweep fetches the *complete* mirror in a single newest→oldest pass: every activity plus all enrichment (detail, laps, comments, kudos, zones) **and all streams**. **No lazy/on-demand fetching** — the agent sees an activity only once the backfill has reached it. MCP tools are pure DB readers; only the background worker calls Strava. |
| OAuth scope | **Full read incl. private** | Request `read_all`, `profile:read_all`, `activity:read_all` (+ `read`, `activity:read`). Captures private / Only-You activities, privacy-zone data, private routes & segments. No write scopes (read-only tool). |
| Re-sync policy | **Insert-only + lookback** | POLL lists `after = newest_synced − 14 days` and **dedupes by activity id**, so back-dated uploads are caught. Existing rows are never re-fetched or mutated; edits/deletes on Strava are **not** reflected. |
| Sync execution | **Server-owned background worker** | The `serve` process runs a self-throttling sweep: newest→oldest backfill until rate-limited, sleep & re-check (~hourly) until the window resets, resume, repeat until backfill complete. Then a 12-hour poll for new activities. Progress logged to terminal **and** a local log file. |
| Transport | **HTTP server** | Long-running FastMCP `streamable-http` server on a local port. Survives across agent sessions; multiple clients can connect. |

## 3. Non-goals

- **No webhooks.** Real-time push requires a public HTTPS callback; out of scope for a local tool.
- **No write operations.** No creating/updating activities, uploads, or starring segments.
- **No edit/delete reconciliation** (per the insert-only decision).
- **No discovery of other athletes** — the API only exposes the authenticated athlete + public/club data.
- **No multi-athlete support** — one Strava account per database.
- **No public segment discovery** — `/segments/explore` (bounding-box search of others' segments) is out of scope; the mirror holds *your* history, not the global segment catalog.
- **No per-segment detail crawl** — encountered segments are kept as embedded summaries; only starred segments get full `DetailedSegment`.
- **No clubs** — club endpoints are skipped entirely (memberships, rosters, and club feeds are not mirrored).
- **No route file export** — routes are stored as metadata + polyline only; no GPX/TCX download.

## 4. Architecture & components

Strictly separated Python modules/packages so sync and serving evolve independently:

```
strava_mcp/
├── config.py          # Settings: client_id/secret, paths, port, scopes, sync window.
│                       #   Loaded from env / .env. No secrets in git.
├── auth/
│   ├── oauth.py        # Authorization-code flow + local callback server on 127.0.0.1.
│   └── tokens.py       # Token storage (in DB), auto-refresh when expires_at is near.
├── client/
│   ├── http.py         # Thin Strava HTTP client: base URL, bearer auth, JSON.
│   └── ratelimit.py    # Reads X-RateLimit/X-ReadRateLimit headers, throttles,
│                       #   backs off on 429 until next 15-min window. Resumable.
├── db/
│   ├── schema.sql      # DDL for raw + normalized tables (section 5).
│   ├── engine.py       # Connection, migrations, WAL mode.
│   └── repositories/   # Typed read/write helpers per resource (activities, athlete…).
├── sync/
│   ├── orchestrator.py # Worker state machine: BOOTSTRAP→BACKFILL→POLL; checkpoints.
│   ├── resources/      # One syncer per resource: athlete, activities (+ enrichment
│   │                   #   & streams), gear, routes, starred segments.
│   └── state.py        # sync_state table: last_activity_epoch, cursors, run log.
├── mcp/
│   ├── server.py       # FastMCP app, HTTP transport, tool registration,
│   │                   #   owns the background sync worker task.
│   └── tools/          # MCP tools (section 7). Pure DB reads — never call Strava.
└── __main__.py         # CLI entrypoints: `auth`, `serve` (sync runs inside serve).
```

**Key principle — dual write.** Every resource fetched is written twice:
1. **Raw** — verbatim API JSON into a `raw_responses` store (backup + future use cases).
2. **Normalized** — parsed into typed tables for efficient MCP querying.

## 5. Data model (SQLite)

### 5.1 Raw store (backup, append-only)

```
raw_responses(
  id INTEGER PK,
  resource_type TEXT,      -- 'activity', 'athlete', 'streams', 'route', ...
  resource_id   TEXT,      -- Strava id (string-safe for gear/route id_str)
  endpoint      TEXT,      -- request path that produced it
  fetched_at    TEXT,      -- ISO-8601
  payload       TEXT       -- raw JSON body
)
```

### 5.2 Normalized tables (for the agent)

**Pattern — lean promoted columns + `detail_json`.** The raw store already holds every
field verbatim, so normalized tables carry only what agents filter/sort/aggregate on; the
rest lives in a `detail_json` column. Each table has:
1. **Keys** — primary key + foreign keys (e.g. `activity_id`).
2. **Promoted columns** (indexed) — the queryable fields only, e.g. for `activities`:
   `start_date`, `start_date_local`, `sport_type`, `name`, `distance`, `moving_time`,
   `elapsed_time`, `total_elevation_gain`, `average_heartrate`, `max_heartrate`,
   `average_watts`, `max_watts`, `average_speed`, `kudos_count`, `comment_count`,
   `gear_id`, `trainer`, `commute`, `private`.
3. **`detail_json`** — the full parsed object for everything else (nested `map`, `photos`,
   `splits_metric/standard`, etc.).

Independently-queried nested collections (`laps`, `segment_efforts`) get their **own** tables
(also lean + `detail_json`); one-off nested blobs stay inside the parent's `detail_json`.
Tools filter via promoted columns and return rich data from `detail_json`. New Strava fields
land in JSON automatically — no migration needed. Unpromoted fields remain queryable via
SQLite `json_extract` (unindexed); the promoted set can be widened cheaply later.

| Table | Source endpoint(s) | Notes |
|-------|--------------------|-------|
| `athlete` | `GET /athlete`, `/athlete/zones`, `/athletes/{id}/stats` | Single row (the authed athlete) + zones + rolled-up stats. |
| `activities` | `GET /athlete/activities`, `GET /activities/{id}` | Summary fields on list; enriched with DetailedActivity on detail fetch. |
| `activity_streams` | `GET /activities/{id}/streams` | Populated by the backfill as part of each activity's enrichment. Stores each stream type as JSON array + metadata (resolution, original_size). |
| `laps` | `GET /activities/{id}/laps` | |
| `comments` | `GET /activities/{id}/comments` | |
| `kudos` | `GET /activities/{id}/kudos` | |
| `activity_zones` | `GET /activities/{id}/zones` | HR/power distribution buckets. |
| `gear` | `GET /gear/{id}` | IDs come from `athlete.bikes`/`shoes`. |
| `routes` | `/athletes/{id}/routes`, `/routes/{id}` | **Metadata only** (includes polyline map). No GPX/TCX export. |
| `segments` | `/segments/starred` (+ embedded in activities) | **Starred** stored as full `DetailedSegment`. **Encountered** segments stored as the `SummarySegment` embedded in activity efforts — **no per-segment `/segments/{id}` upgrade call** (avoids an unbounded crawl). |
| `segment_efforts` | (embedded in `DetailedActivity`) | **No standalone sweep.** The athlete's efforts come from each activity's `segment_efforts[]` + `best_efforts[]` during enrichment. |
| `sync_state` | (internal) | Last synced activity epoch, per-resource cursors, run history, rate-limit snapshots. |

Indexes on `activities(start_date)`, `activities(sport_type)`, `segment_efforts(segment_id)`, etc.

## 6. Sync behavior

Sync runs as a **background worker inside the `serve` process** (not a one-shot CLI
run). It is self-throttling and self-resuming — it never needs babysitting.

### 6.1 Worker state machine
The worker tracks two cursors in `sync_state`:
- **backfill frontier** — the oldest activity synced so far (the sweep moves this older).
- **newest synced** — the newest activity synced (the poll moves this newer).

```
BOOTSTRAP   → fetch athlete profile, zones, stats, gear, routes, starred segments
BACKFILL    → page /athlete/activities newest→oldest, enriching each activity,
              advancing the backfill frontier; checkpoint after every page
   │ rate-limited?
   ├─ yes → COOLDOWN: sleep, re-check (~hourly) until the window resets → BACKFILL
   └─ frontier reached the first-ever activity → backfill complete
POLL        → every 12h: /athlete/activities?after=<newest_synced − 14 days>,
              dedupe by activity id, enrich+insert only ids not already stored,
              advance newest cursor (catches back-dated uploads; never mutates rows)
```

### 6.2 Backfill direction & enrichment
- Newest activities are synced **first** so the agent has useful recent data early,
  even while older history is still streaming in.
- Each activity is **fully enriched in one pass** as the frontier reaches it:
  DetailedActivity → laps → comments → kudos → zones → **streams**. An activity is
  written only as a complete unit, so what's in the DB is always fully synced.
- **No lazy/on-demand fetching.** An activity is invisible to the agent until the
  backfill has reached and enriched it.

### 6.3 Rate limiting (cross-cutting)
- After each response, read `X-ReadRateLimit-Usage` / `X-RateLimit-Usage` to track budget.
- The 15-min window resets on the quarter hour; the daily window at midnight UTC — both
  are **deterministic**, so COOLDOWN sleeps until the *known* next reset rather than
  guessing (the ~hourly re-check is the upper bound, not a blind poll).
- On `429`, back off to the next window boundary, then resume from the last checkpoint.

### 6.4 Definition of "fully synced"
The backfill is **complete** when the frontier has reached the athlete's first-ever
activity and every activity carries its full enrichment **including streams**. Only
then does the worker switch to the 12-hour POLL. "Fully synced" = athlete profile +
every activity + all enrichment + all streams present locally.

### 6.5 Logging
- Progress (current activity, frontier date, rate-limit budget, cooldown ETA) is written
  to **stdout** (the terminal running `serve`) and a **local log file** (gitignored).

## 7. MCP tools (read surface for the agent)

Exposed via FastMCP. Every tool is a **pure read against SQLite** — none call Strava.
Data an activity exposes is whatever the backfill has already written; for an activity
the frontier hasn't reached yet, tools simply return "not yet synced".

- `get_athlete()` — profile, zones, stats.
- `list_activities(after?, before?, sport_type?, limit?)` — filtered activity summaries.
- `get_activity(id)` — full DetailedActivity (laps, splits, best efforts, gear).
- `get_activity_streams(id, keys?)` — returns the stored streams (or "not yet synced").
- `get_activity_zones(id)` / `get_laps(id)` / `get_comments(id)` / `get_kudos(id)`.
- `list_gear()` / `get_gear(id)`.
- `list_routes()` / `get_route(id)`.
- `list_starred_segments()` / `get_segment(id)` / `list_segment_efforts(segment_id)`.
- `sync_now()` — nudge the background worker to run the forward POLL immediately.
- `sync_status()` — backfill frontier date, % complete, fully-synced flag, counts, current rate-limit budget, cooldown ETA.
- Aggregate helpers (DB-side, cheap): e.g. `summarize_training(period, sport_type?)`.

## 8. Tooling, configuration & secrets

- **Package/runtime manager: `uv`.** Project defined in `pyproject.toml`; deps locked in `uv.lock`.
  Entrypoints run via `uv run strava-mcp <auth|serve>` (sync runs inside `serve`).
- Config loaded from a `.env` file (see committed `.env.example` for the template):
  - `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` — from <https://www.strava.com/settings/api>.
  - `STRAVA_ACCESS_TOKEN`, `STRAVA_REFRESH_TOKEN`, `STRAVA_TOKEN_EXPIRES_AT`, `STRAVA_TOKEN_SCOPE` — bootstrap seed tokens.
  - `STRAVA_SCOPES`, `OAUTH_REDIRECT_HOST`, `OAUTH_REDIRECT_PORT` — OAuth flow.
  - `STRAVA_DB_PATH` (default `./.database/strava.db`), `MCP_HOST`, `MCP_PORT`, `SYNC_MAX_REQUESTS`.
- **Tokens are persisted in the DB** after first auth; `.env` only seeds the initial run.
- `.gitignore` excludes `.database/`, `.env`, and `.venv/`.

> **Bootstrap caveat:** the seed token currently in `.env` has `scope=read` only and
> cannot list activities/streams. `uv run strava-mcp auth` must complete the full
> OAuth authorize flow (requesting `STRAVA_SCOPES`) to mint a refresh token with the
> broader scopes before sync can fetch activities.

### 8.1 Startup & auth
- **`serve` requires a full-scope token.** On boot it checks the stored token's scope; if
  the required scopes are missing it **exits with instructions** (`run uv run strava-mcp auth`)
  rather than auto-launching auth. `auth` is a deliberate, separate step.
- **`auth`** builds the authorize URL from `STRAVA_SCOPES`, **opens the browser** (falls back
  to printing the URL when headless), runs the local callback server on
  `127.0.0.1:${OAUTH_REDIRECT_PORT}` to **auto-capture the `code`** (no copy-paste), exchanges
  it for tokens, **persists them in the DB**, and verifies with
  `GET /athlete/activities?per_page=1` that the scope actually works.
- **Token precedence:** DB-stored tokens override the `.env` seed once present. The worker
  silently refreshes the access token (~6h life) via the refresh token before expiry.

### 8.2 Operational defaults
- **Process model:** the sync worker runs as a **dedicated thread** inside `serve`. SQLite in
  **WAL mode** with a **single writer** (only the worker writes; MCP tools are concurrent
  readers) — no write contention.
- **Transport security:** the FastMCP HTTP server **binds `127.0.0.1` only** (loopback,
  single-user local); no network auth layer.
- **Logging:** progress logged to stdout and a rotating file at **`./.database/strava-mcp.log`**
  (gitignored alongside the DB).

## 9. Open items / future use cases

- Optional GPX/TCX export caching for routes & activities.
- Optional webhook mode (requires tunneling) to upgrade to real-time + edit/delete tracking.
- Optional clubs support (memberships) if ever wanted — currently out of scope.
- On-demand per-segment `DetailedSegment` upgrade tool for encountered segments.
- Derived analytics tables (weekly mileage, PRs, zone distribution over time).

## 10. Suggested milestones

1. **M1 — Foundations & auth:** `uv` project, config, DB schema (raw + lean normalized),
   engine (WAL), `auth` command (full-scope OAuth, browser + local callback, token
   persistence/refresh), `serve` scope-check-or-exit.
2. **M2 — Strava client & rate limiter:** `httpx` client, budget tracking from rate headers,
   deterministic cooldown/backoff to the next window, resumable checkpoints.
3. **M3 — Background backfill worker:** BOOTSTRAP (athlete/zones/stats/gear/routes/starred)
   + newest→oldest activity backfill with full enrichment **and streams**; `sync_state`
   cursors; dual logging (stdout + rotating file).
4. **M4 — MCP server (pure readers):** FastMCP HTTP transport on loopback + read tools over
   the DB; `sync_status` / `sync_now`; POLL loop (12h, 14-day lookback, dedupe-by-id).
5. **M5 — Aggregates & polish:** `summarize_training` and friends, README, docs.
