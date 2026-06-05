# Quickstart & Validation: Local Data Dashboard

A run-and-verify guide proving the dashboard works end-to-end against a populated mirror. Implementation
details live in `tasks.md`; interface details in `contracts/` and `data-model.md`.

## Prerequisites

- The project is set up with `uv` (Python 3.11+), dependencies installed (`uv sync`).
- A mirror already exists and has at least some **enriched** activities — i.e. `uv run strava-mcp auth`
  was completed and `uv run strava-mcp serve` has run long enough to backfill some activities (with
  streams). The dashboard reads this database read-only; it does not create or populate it.

## Run

```bash
# Optionally override the loopback port (default 8722)
# export DASHBOARD_PORT=8722
uv run strava-mcp dashboard
```

Expected: a log line like `dashboard on http://127.0.0.1:8722`. Open that URL in a browser.

The dashboard can run **at the same time** as `uv run strava-mcp serve` (separate terminal/process).

## Validation scenarios

Each maps to a spec user story / success criterion.

### US1 — Activity list (P1, SC-001/002)
1. Open `/`. The activity list appears within ~10s, newest-first, showing date, sport type, name,
   distance, moving time, elevation, and HR/power where present.
2. Add `?sport_type=Run` (or use the filter control) → only runs remain; the result count updates.
3. Add `?after=2024-01-01&before=2024-12-31` → only that year's activities remain.
4. Confirm the visible count/rows match what the mirror holds for those filters (cross-check with the
   `list_activities` MCP tool or a direct `SELECT` on enriched rows).
5. Paginate with `?page=2` on a large mirror — the page stays responsive (FR-015).

### US2 — Activity detail + graphs (P2, SC-003/006)
1. Click an activity (`/activity/{id}`). Summary metrics, laps, segment efforts, and zone distribution
   match the stored values.
2. Inline-SVG graphs render for each present stream type within ~2s; no graph appears for stream types
   the activity lacks.
3. Open an activity with no streams (e.g. a manual entry) → a clear "no stream data" note, no error.
4. Request a non-existent or not-yet-enriched id → a "not found / not yet synced" page (404), not a
   stack trace.

### US3 — Timeline (P3, SC-002)
1. Open `/timeline`. Default monthly buckets show count/distance/moving-time/elevation totals.
2. Switch `?period=week` and `?period=year` → buckets and totals recompute.
3. A month/week/year with no activities appears as a zero bucket (gaps visible), not dropped.
4. Bucket totals equal the sum of matching enriched activities for that period.

### US4 — Sync progress (P4, SC-004)
1. Open `/sync`. It shows the current phase, frontier date, percent-complete, stored-activity count,
   rate-limit budget, and cooldown ETA (if any).
2. With `serve` running, let the worker advance, then **reload** `/sync` → figures update (no
   auto-refresh in v1).
3. With `serve` stopped, `/sync` still loads and shows the last persisted state.

### Cross-cutting (SC-005/006/007)
- While a backfill is running, browsing the dashboard causes no observable slowdown/lock contention for
  the worker (read-only WAL connections).
- No view shows a partially-enriched activity; the dashboard issues zero Strava requests.
- Edge cases each produce an informative message, not a crash:
  - Empty mirror → empty states on every page.
  - DB missing → `No mirror found at <path>. Run 'uv run strava-mcp serve' first ...` (exit 1).
  - Port in use → `Port <n> is in use. Set DASHBOARD_PORT to a free port and retry.` (exit 1).

## Automated tests (offline)

Run the dashboard test suite (real temp SQLite fixtures in WAL mode; no live Strava):

```bash
uv run pytest tests/dashboard -q
uv run ruff check strava_mcp/dashboard
uv run mypy strava_mcp
```

The pure-reader guard test asserts `strava_mcp.dashboard` imports neither `strava_mcp.client` nor
`strava_mcp.sync`.
