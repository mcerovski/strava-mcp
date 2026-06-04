# Phase 0 Research: Strava MCP Local Mirror

The PRD, CONTEXT glossary, and ADRs 0001–0003 already fix the load-bearing architecture
decisions. This document records the remaining technical resolutions (library micro-choices
and a few mechanics) so Phase 1 design has no open `NEEDS CLARIFICATION`. Each item is
**Decision / Rationale / Alternatives considered**.

## Already-ratified decisions (carried in, not re-litigated)

- **Pure-reader MCP + one unified background backfill** — ADR 0001. Tools never call Strava;
  one worker code path (BOOTSTRAP → newest→oldest BACKFILL w/ enrichment incl. streams →
  12h POLL). No lazy/on-demand fetch.
- **Lean promoted columns + `detail_json`; append-only `raw_responses`** — ADR 0002.
- **Insert-only sync with 14-day poll lookback, dedupe-by-id** — ADR 0003.
- **Full read scopes, loopback-only HTTP, tokens in DB** — PRD §2, §8.

## R1. MCP server framework

**Decision**: `fastmcp` with the `streamable-http` transport, bound to `127.0.0.1:${MCP_PORT}`.

**Rationale**: PRD mandates FastMCP HTTP transport surviving across agent sessions with
multiple concurrent clients. `streamable-http` is the long-running HTTP transport; loopback
bind satisfies the single-user/no-auth constraint. The server process owns the background
worker thread (PRD §8.2).

**Alternatives considered**: stdio transport (rejected — dies with the client session, can't
host a long-running backfill or serve multiple clients); SSE-only (superseded by
streamable-http).

## R2. HTTP client & rate-limit header parsing

**Decision**: `httpx` (sync client inside the worker thread). After each response, read
`X-ReadRateLimit-Usage`/`X-ReadRateLimit-Limit` (and the overall `X-RateLimit-*`), both
formatted `15min,daily`. Track the Read tier as the binding budget (it is the tighter limit
for this read-only tool: 100/15min, 1000/day).

**Rationale**: `httpx` gives explicit response headers, timeouts, and a clean place to hook
token refresh + budget accounting. The worker is single-threaded for writes, so a sync client
is simpler than async and avoids event-loop coupling with FastMCP.

**Alternatives considered**: `requests` (no native async story if ever needed; httpx is the
modern default); aiohttp (async complexity unjustified for a serial crawler).

## R3. Deterministic cooldown computation

**Decision**: On budget exhaustion or `429`, sleep until the **known** next reset:
- 15-min window: next quarter-hour boundary (`:00/:15/:30/:45`) in UTC.
- Daily window: next midnight UTC.
Choose the soonest reset that frees the exhausted tier; on `429` without usable headers,
fall back to the next quarter-hour. Re-check at most ~hourly as an upper bound, never a blind
poll. Resume from the last checkpoint.

**Rationale**: PRD §6.3 / Constitution IV require deterministic waits, not retry loops. Both
windows have fixed, computable boundaries (API.md §3), so the wait is exact.

**Alternatives considered**: exponential backoff (rejected — non-deterministic, wastes the
known reset time); fixed sleep (rejected — either too long or 429-storms).

## R4. Token storage & refresh

**Decision**: Persist `access_token`, `refresh_token`, `expires_at`, `scope` in a `tokens`
table (single row). On each worker request, if `expires_at` is within a refresh margin
(~5 min), refresh via `POST /oauth/token` (`grant_type=refresh_token`) and **persist the
returned refresh_token** (it may rotate). DB tokens override the `.env` seed once present.

**Rationale**: PRD §8.1 + API.md §1.3. Storing in DB (not `.env`) keeps the running secret of
record inside `./.database/` and lets `auth` seed once.

**Alternatives considered**: keep tokens in `.env` (rejected — secret churn in a gitignored
file the worker would have to rewrite; DB is the source of truth per PRD).

## R5. OAuth local callback capture

**Decision**: `auth` builds the authorize URL from `STRAVA_SCOPES`, opens it via
`webbrowser.open` (falls back to printing when headless), and runs a one-shot
`http.server` listener on `127.0.0.1:${OAUTH_REDIRECT_PORT}` that captures the `code` (and
returned `scope`) from the redirect, exchanges it for tokens, persists them, then verifies
with `GET /athlete/activities?per_page=1`. A `state` value guards against CSRF.

**Rationale**: PRD §8.1 / API.md §1.1. `127.0.0.1` is whitelisted by Strava for dev redirect
URIs, so no tunneling is needed. Auto-capture removes copy-paste.

**Alternatives considered**: manual copy-paste of the code (rejected by PRD — must auto-capture);
device/PKCE flow (Strava only offers the authorization-code flow).

## R6. Scope verification at `auth` and `serve`

**Decision**: Required scope set = `read`, `read_all`, `profile:read_all`, `activity:read`,
`activity:read_all` (the `.env.example` default). `auth` checks the **granted** scope from the
redirect (users can uncheck boxes) and warns if narrowed. `serve` reads the stored token's
scope on boot; if any required scope is missing it exits printing
`run uv run strava-mcp auth` and does not auto-launch auth.

**Rationale**: PRD §8 + API.md §1.1 ("always check granted scope"). Private/Only-You data and
zones need `*_all` scopes; the seed token may be `read`-only (PRD bootstrap caveat).

**Alternatives considered**: auto-launch auth from serve (rejected — PRD wants auth as a
deliberate separate step).

## R7. Streams storage shape

**Decision**: Fetch with `keys=<types>&key_by_type=true`. Store one `activity_streams` row
per activity holding the stream set as JSON (each type → `{data:[...], series_type,
original_size, resolution}`) plus top-level metadata. Stream types pursued: `time, distance,
latlng, altitude, velocity_smooth, heartrate, cadence, watts, temp, moving, grade_smooth`.

**Rationale**: PRD §5.2 / Constitution IV — streams are the volume; per-sample rows would
explode the DB and slow reads. JSON arrays keyed by type match how `get_activity_streams`
returns them and how Strava delivers `key_by_type`.

**Alternatives considered**: per-sample rows (rejected — millions of rows, no query benefit);
separate row per stream type (acceptable but a single per-activity row is simpler to write
atomically as part of single-unit enrichment).

## R8. Activity visibility / single-unit enrichment

**Decision**: Add an `enriched_at` (nullable) column on `activities`. An activity row is
inserted during backfill paging (summary) but is **agent-visible only when `enriched_at IS
NOT NULL`**. Enrichment writes all facets (detail, laps, comments, kudos, zones, streams,
segment_efforts) in one transaction that finally stamps `enriched_at`. Read tools filter on
`enriched_at IS NOT NULL`; unreached/unenriched → `not yet synced`.

**Rationale**: Constitution III ("partial data never exposed") + CONTEXT enrichment definition.
A visibility flag set last in a transaction is the simplest atomic "complete unit" guarantee.

**Alternatives considered**: staging table then move (rejected — extra copy, no benefit under
WAL single-writer); rely on row existence (rejected — summary rows exist pre-enrichment).

## R9. Frontier / newest-synced cursors & "fully synced"

**Decision**: `sync_state` holds `backfill_frontier_epoch` (oldest enriched start_date),
`newest_synced_epoch` (newest enriched start_date), `backfill_complete` flag, and per-run
log + rate-limit snapshots. Backfill is **complete** when paging `/athlete/activities` returns
no older activity (reached first-ever) AND every activity has `enriched_at` set incl. streams.
`sync_status` % complete = enriched_count / total_listed (best-effort; total grows as paging
discovers history).

**Rationale**: CONTEXT "fully synced" + PRD §6.4. Cursors in epoch seconds match Strava's
`after`/`before` (start_date based, ADR 0003).

**Alternatives considered**: track by page number (rejected — back-dated uploads shift pages;
epoch on start_date is stable for the poll's `after` math).

## R10. Config loading

**Decision**: `pydantic-settings` (`BaseSettings`) for `config.py` — typed env/.env loading
with defaults matching `.env.example`. If avoiding a dependency is preferred, a stdlib
`dataclass` + `os.environ` reader is an acceptable fallback; default to `pydantic-settings`
for validation and typed boundaries (Constitution I).

**Rationale**: Typed config with `.env` support and clear errors on missing client creds.

**Alternatives considered**: bare `os.environ` (works but no validation/typing); `python-dotenv`
alone (no typing).

## R11. Logging (dual sink + rotation)

**Decision**: stdlib `logging` with two handlers: `StreamHandler` (stdout) and
`RotatingFileHandler` at `./.database/strava-mcp.log`. A redaction filter scrubs token-like
values. Worker logs current activity, frontier date, rate-limit budget, cooldown ETA.

**Rationale**: PRD §6.5 / §8.2 + Constitution (no secrets in logs). Stdlib avoids a dep.

**Alternatives considered**: `structlog`/`loguru` (nice but an unneeded dependency for a
single-process tool).

## R12. Concurrency model (worker thread + WAL)

**Decision**: One dedicated worker **thread** inside `serve` is the sole writer; FastMCP tool
calls open their own read-only SQLite connections. WAL mode (`PRAGMA journal_mode=WAL`) lets
readers proceed during writes. Each thread/connection is independent (SQLite connections are
not shared across threads).

**Rationale**: PRD §8.2. Single writer + WAL = no write contention; concurrent agent reads
never block the worker and vice versa (Constitution IV).

**Alternatives considered**: separate process for sync (rejected — PRD wants worker inside
serve; IPC overkill); async single-loop (rejected — mixing the long crawler with the MCP loop
complicates cancellation and the blocking cooldown sleeps).

## R13. Test fixtures from the OpenAPI spec

**Decision**: Build recorded JSON fixtures under `tests/fixtures/` shaped to the models in
`strava-api-spec/swagger/*.json` (activity, athlete, lap, comment, segment, segment_effort,
stream, zones, gear, route). Tests load these to drive syncers; the rate limiter and cooldown
are tested with synthesized headers and an injectable clock.

**Rationale**: Constitution II — no live Strava calls; deterministic offline tests within
budget. The committed spec is the contract source of truth.

**Alternatives considered**: VCR-style live recording (rejected — needs a live account/token
and risks committing private data); hand-mocking at the function level (rejected — DB tests
must use a real temp SQLite).

## R14. Type checking & lint

**Decision**: `ruff` for lint + format; `mypy` (strict on `strava_mcp/`) for type checking,
run via `uv`. (`pyright` is an acceptable substitute.)

**Rationale**: Constitution I requires clean static checks and typed public boundaries.

**Alternatives considered**: lint-only (rejected — type errors at module boundaries are exactly
what the "typed boundaries" rule targets).

---

**Outcome**: All Technical Context items resolved; zero open `NEEDS CLARIFICATION`. Ready for
Phase 1 design.
