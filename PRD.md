# strava-mcp — Product Requirements Document (PRD)

> A locally-run Python MCP server that gives AI agents read access to your full
> Strava history, backed by a local SQLite database that mirrors the Strava API.

Status: **draft / pre-implementation** · Runtime: Python 3.11+ managed by [`uv`](https://docs.astral.sh/uv/) · API: [Strava API v3](./API.md)

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
| Stream sync | **Lazy + cache** | Initial sync pulls activity list + details. Per-second streams (HR, watts, latlng, altitude, cadence…) are fetched on the first MCP request for an activity, then cached in DB permanently. |
| OAuth scope | **Full read incl. private** | Request `read_all`, `profile:read_all`, `activity:read_all` (+ `read`, `activity:read`). Captures private / Only-You activities, privacy-zone data, private routes & segments. No write scopes (read-only tool). |
| Re-sync policy | **Insert-only** | Each sync fetches only activities newer than the last synced one (`after=<epoch>`). Already-stored activities are never re-fetched; edits/deletes on Strava are **not** reflected. |
| Transport | **HTTP server** | Long-running FastMCP `streamable-http` server on a local port. Survives across agent sessions; multiple clients can connect. |

## 3. Non-goals

- **No webhooks.** Real-time push requires a public HTTPS callback; out of scope for a local tool.
- **No write operations.** No creating/updating activities, uploads, or starring segments.
- **No edit/delete reconciliation** (per the insert-only decision).
- **No discovery of other athletes** — the API only exposes the authenticated athlete + public/club data.
- **No multi-athlete support** — one Strava account per database.

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
│   ├── orchestrator.py # Drives full + incremental sync; checkpoints progress.
│   ├── resources/      # One syncer per resource: athlete, activities, clubs,
│   │                   #   gear, routes, segments, segment_efforts, streams.
│   └── state.py        # sync_state table: last_activity_epoch, cursors, run log.
├── mcp/
│   ├── server.py       # FastMCP app, HTTP transport, tool registration.
│   └── tools/          # MCP tools (section 6). Query DB; lazy-fetch streams.
└── __main__.py         # CLI entrypoints: `sync`, `serve`, `auth`.
```

**Key principle — dual write.** Every resource fetched is written twice:
1. **Raw** — verbatim API JSON into a `raw_responses` store (backup + future use cases).
2. **Normalized** — parsed into typed tables for efficient MCP querying.

## 5. Data model (SQLite)

### 5.1 Raw store (backup, append-only)

```
raw_responses(
  id INTEGER PK,
  resource_type TEXT,      -- 'activity', 'athlete', 'streams', 'club', ...
  resource_id   TEXT,      -- Strava id (string-safe for gear/route id_str)
  endpoint      TEXT,      -- request path that produced it
  fetched_at    TEXT,      -- ISO-8601
  payload       TEXT       -- raw JSON body
)
```

### 5.2 Normalized tables (for the agent)

One table per major resource, columns mirroring the [Data models](./API.md#6-data-models).
Full-fidelity numeric fields kept (distance, moving/elapsed time, elevation, watts, HR…).

| Table | Source endpoint(s) | Notes |
|-------|--------------------|-------|
| `athlete` | `GET /athlete`, `/athlete/zones`, `/athletes/{id}/stats` | Single row (the authed athlete) + zones + rolled-up stats. |
| `activities` | `GET /athlete/activities`, `GET /activities/{id}` | Summary fields on list; enriched with DetailedActivity on detail fetch. |
| `activity_streams` | `GET /activities/{id}/streams` | **Lazy** — populated on first request. Stores each stream type as JSON array + metadata (resolution, original_size). |
| `laps` | `GET /activities/{id}/laps` | |
| `comments` | `GET /activities/{id}/comments` | |
| `kudos` | `GET /activities/{id}/kudos` | |
| `activity_zones` | `GET /activities/{id}/zones` | HR/power distribution buckets. |
| `gear` | `GET /gear/{id}` | IDs come from `athlete.bikes`/`shoes`. |
| `clubs` | `/athlete/clubs`, `/clubs/{id}` (+ members/admins/activities) | |
| `routes` | `/athletes/{id}/routes`, `/routes/{id}` | + optional GPX/TCX export blobs. |
| `segments` | `/segments/starred`, `/segments/{id}` | Starred + any explored/encountered. |
| `segment_efforts` | `/segment_efforts`, `/segment_efforts/{id}` | The athlete's efforts per segment. |
| `sync_state` | (internal) | Last synced activity epoch, per-resource cursors, run history, rate-limit snapshots. |

Indexes on `activities(start_date)`, `activities(sport_type)`, `segment_efforts(segment_id)`, etc.

## 6. Sync behavior

### 6.1 First run (full sync)
1. Ensure auth (run `auth` flow if no valid token).
2. Fetch athlete profile, zones, stats, clubs, gear, routes, starred segments.
3. Page through `GET /athlete/activities` (oldest→newest), storing summaries + DetailedActivity, laps, comments, kudos, zones.
4. **Streams skipped** (lazy). Record the newest `start_date` epoch in `sync_state`.
5. Checkpoint after every page so the run is **resumable** if a 429 / interruption hits.

### 6.2 Subsequent runs (incremental, insert-only)
- `GET /athlete/activities?after=<last_synced_epoch>` → only newer activities.
- Enrich + store as above. Advance the checkpoint. No re-fetch of existing rows.

### 6.3 Rate limiting (cross-cutting)
- Before each request, check remaining budget from the last response's `X-ReadRateLimit-Usage`.
- On `429`, sleep until the next quarter-hour boundary, then resume.
- Configurable max-requests-per-run cap so a huge backlog can be synced over multiple sessions.

## 7. MCP tools (read surface for the agent)

Exposed via FastMCP. Each queries SQLite; stream tools lazy-fetch + cache on miss.

- `get_athlete()` — profile, zones, stats.
- `list_activities(after?, before?, sport_type?, limit?)` — filtered activity summaries.
- `get_activity(id)` — full DetailedActivity (laps, splits, best efforts, gear).
- `get_activity_streams(id, keys?)` — **lazy**: returns cached streams or fetches, stores, returns.
- `get_activity_zones(id)` / `get_laps(id)` / `get_comments(id)` / `get_kudos(id)`.
- `list_clubs()` / `get_club(id)` / `list_club_activities(id)`.
- `list_gear()` / `get_gear(id)`.
- `list_routes()` / `get_route(id)` (+ export).
- `list_starred_segments()` / `get_segment(id)` / `list_segment_efforts(segment_id)`.
- `sync_now(mode?)` — trigger an incremental sync from the agent.
- `sync_status()` — last sync time, counts, current rate-limit budget.
- Aggregate helpers (DB-side, cheap): e.g. `summarize_training(period, sport_type?)`.

## 8. Tooling, configuration & secrets

- **Package/runtime manager: `uv`.** Project defined in `pyproject.toml`; deps locked in `uv.lock`.
  Entrypoints run via `uv run strava-mcp <auth|sync|serve>`.
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

## 9. Open items / future use cases

- Optional GPX/TCX export caching for routes & activities.
- Optional webhook mode (requires tunneling) to upgrade to real-time + edit/delete tracking.
- Backfill streams in bulk (opt-in) for offline analysis.
- Derived analytics tables (weekly mileage, PRs, zone distribution over time).

## 10. Suggested milestones

1. **M1 — Foundations:** config, DB schema, raw store, OAuth + token refresh.
2. **M2 — Sync engine:** rate-limited client, full + incremental activity sync (no streams).
3. **M3 — MCP server:** FastMCP HTTP transport, core read tools over the DB.
4. **M4 — Lazy streams + remaining resources:** clubs, gear, routes, segments, efforts.
5. **M5 — Aggregates & polish:** summary tools, sync_status, docs.
