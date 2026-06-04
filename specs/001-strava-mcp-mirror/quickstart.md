# Quickstart & Validation Guide: Strava MCP Local Mirror

Runnable validation scenarios that prove the feature works end-to-end. Details live in
[plan.md](./plan.md), [data-model.md](./data-model.md), and
[contracts/](./contracts/). Implementation code belongs in `tasks.md` / the build phase, not here.

## Prerequisites

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) installed.
- A Strava API application (`client_id` / `client_secret`) from
  <https://www.strava.com/settings/api>, with the callback domain allowing `127.0.0.1`.
- A `.env` file copied from `.env.example` with `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET`
  filled in. (Other values default sensibly; see [contracts/cli.md](./contracts/cli.md).)

## Setup

```bash
cp .env.example .env       # then edit in your client_id / client_secret
uv sync                    # install locked dependencies
```

## Scenario 1 — Authorize once (US1, PLAN slice 1)

```bash
uv run strava-mcp auth
```
**Expected**: a browser opens to Strava's consent screen for the full read scopes (URL is
printed if headless); after approval the callback auto-captures the code (no copy-paste);
tokens are written to the DB; the command verifies with a 1-activity probe read and prints the
granted scopes. Exit code `0`.

**Validates**: credentials persisted in `tokens`; DB overrides `.env` seed; probe read succeeds.

## Scenario 2 — Serve + athlete read (US2, PLAN slice 2)

```bash
# Negative: an under-scoped token must refuse to serve
uv run strava-mcp serve        # with a read-only seed token
#   → exits non-zero printing: run uv run strava-mcp auth

# Positive: with a full-scope token
uv run strava-mcp serve        # starts MCP server on 127.0.0.1:8720 + worker thread
```
From an MCP client pointed at `http://127.0.0.1:8720`, call `get_athlete()`.
**Expected**: profile + zones + stats returned from the DB (no Strava call by the tool).

**Validates**: scope-check-or-exit; loopback bind; BOOTSTRAP dual-write; pure-reader tool.

## Scenario 3 — Activity backfill, filters, resume, status (US3, PLAN slice 3)

- Let `serve` run; the worker pages activities newest→oldest.
- `list_activities(after=..., before=..., sport_type="Run", limit=10)` → only matching,
  already-enriched activities, newest first.
- `sync_status()` → plausible `frontier_date`, `percent_complete`, counts, `rate_limit`.
- Stop (`Ctrl-C`) mid-backfill and restart `serve`.
  **Expected**: it resumes from the frontier with **zero re-fetch** of stored activities.
- Drive the worker to the read budget (in tests, via synthesized rate-limit headers).
  **Expected**: it cools down to the known next reset and resumes automatically; `sync_status`
  shows `cooldown_until`.

**Validates**: FR-009, FR-015, FR-020, FR-021; checkpoint/resume; deterministic cooldown.

## Scenario 4 — Enrichment facets (US4, PLAN slice 4)

For an enriched activity id `A`:
`get_activity(A)`, `get_laps(A)`, `get_comments(A)`, `get_kudos(A)`, `get_activity_zones(A)`.
**Expected**: full detail + each facet returned; `list_segment_efforts(<seg>)` shows efforts
captured from the activity. For an activity the frontier hasn't reached → `not yet synced`.

**Validates**: single-unit enrichment; no partial activity exposed; embedded efforts populated.

## Scenario 5 — Streams + fully-synced (US5, PLAN slice 5)

- `get_activity_streams(A)` → per-type streams with metadata; `get_activity_streams(A,
  keys=["heartrate","watts"])` → only those types.
- For an unreached activity → `not yet synced`.
- Once frontier reaches the first-ever activity and all carry streams → `sync_status()`
  `fully_synced = true`.

**Validates**: FR-019, FR-020; fully-synced flips only after streams present.

## Scenario 6 — Gear, routes, starred segments (US6, PLAN slice 6)

`list_gear()` / `get_gear(id)`; `list_routes()` / `get_route(id)` (metadata + polyline, no
file export); `list_starred_segments()`; `get_segment(id)` → detail for a starred segment,
embedded summary for an encountered one (no extra fetch).

**Validates**: FR-012, FR-013, FR-019.

## Scenario 7 — Steady-state poll + nudge (US7, PLAN slice 7)

With a fully-synced mirror: `sync_now()` → runs the forward POLL immediately. Add a new (and a
back-dated-within-14-days) activity in the fixture and confirm it is enriched + inserted, while
existing rows are untouched (insert-only).

**Validates**: FR-016, FR-017, FR-018; 14-day lookback + dedupe-by-id; no mutation.

## Scenario 8 — Training summary (US8, PLAN slice 8)

`summarize_training(period="weekly")` and `summarize_training(period="monthly",
sport_type="Ride")`.
**Expected**: counts / distance / time / elevation rollups that match the underlying
activities (computed in SQL).

**Validates**: FR-022.

## Test execution (offline, deterministic — Constitution II)

```bash
uv run pytest            # all tests; uses temp SQLite (WAL) + recorded fixtures, no live API
uv run ruff check .      # lint
uv run mypy strava_mcp   # type check
```
No test contacts the live Strava API; fixtures derive from `strava-api-spec/`. The pure-reader
guard test asserts `strava_mcp/mcp/tools/` imports neither `client` nor `sync`.
