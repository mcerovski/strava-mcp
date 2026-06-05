# Implementation Plan: Local Data Dashboard

**Branch**: `002-dashboard` | **Date**: 2026-06-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-dashboard/spec.md`

## Summary

Add a `dashboard` subcommand (`uv run strava-mcp dashboard`) that serves a local, browser-based,
**read-only** view of the mirrored Strava data: an activity list (filterable, paginated), a
per-activity detail page (summary + laps + segment efforts + HR/power zones + stream graphs), a
week/month/year timeline of aggregate training volume, an athlete header, and a sync-progress page.
The dashboard is a **fourth pure-reader surface** alongside the MCP tools — it never calls Strava and
never writes to the mirror. It runs as its own process, reading the same WAL SQLite database that
`serve` populates via read-only connections, so it never blocks the single writer.

Technical approach (resolved in [research.md](./research.md)): serve with the **Python standard-library
HTTP server** (no new dependency), render **server-side HTML** with **inline SVG charts generated in
Python** (no JavaScript framework, no CDN, no map tiles — fully offline per the no-external-network
posture), drive filters/grouping/pagination through query-string parameters, and read all data through
the existing `repositories/` layer (extended with the few read methods the dashboard needs).

## Technical Context

**Language/Version**: Python 3.11+ (matches the existing package; `requires-python = ">=3.11"`).

**Primary Dependencies**: Standard library only for the new surface — `http.server`
(`ThreadingHTTPServer`), `html`, `xml`/string building for SVG, `urllib.parse`. Reuses the existing
`strava_mcp.db` engine + `repositories/` layer and `pydantic-settings` config. **No new third-party
dependency is added.**

**Storage**: The existing local SQLite mirror (WAL), opened via `engine.read_only_connect` — same
read pattern as the MCP tools. No schema changes, no new tables.

**Testing**: `pytest` (existing). DB/query tests run against a real temp SQLite file in WAL mode
(Constitution II); render/HTTP handler tests run against fixture databases; a guard test asserts the
dashboard module imports neither `strava_mcp.client` nor `strava_mcp.sync` (pure-reader boundary).

**Target Platform**: Local Linux/macOS/Windows; loopback `127.0.0.1` only, viewed in a modern browser
on the same machine.

**Project Type**: Single project — a new `strava_mcp/dashboard/` module (sibling to `mcp/`), plus a
`dashboard` CLI subcommand. Web UI is server-rendered; there is no separate frontend build.

**Performance Goals**: Activity list visible < 10s after launch (SC-001); activity graphs render < 2s
on a multi-year mirror (SC-003) via stream downsampling; list/timeline stay responsive at thousands of
activities (FR-015) via SQL pagination/aggregation.

**Constraints**: Read-only (no writes, no Strava calls); loopback bind only; no external network at
runtime (assets and charts are local/inline); must not block the sync worker (read-only WAL
connections, no write locks); must not render tokens/secrets; UI text uses the fixed vocabulary.

**Scale/Scope**: Single athlete, single local user. Five views (list, detail, timeline, sync, athlete
header). Mirrors of up to tens of thousands of activities and large per-activity streams.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Code Quality & Architectural Integrity — PASS
- **Module separation preserved**: a new `strava_mcp/dashboard/` module evolves independently; it is a
  pure reader like `mcp/`. It MUST NOT call Strava and MUST NOT write the DB.
- **Typed boundaries via repositories**: the dashboard reads through the `repositories/` layer
  (extended with the read methods below), not ad-hoc SQL scattered in handlers. Public functions carry
  type hints and pass `ruff`/`mypy --strict`.
- **No dual-write concern**: the dashboard writes nothing, so the dual-write rule is N/A (it is a
  reader of the rebuildable projection).
- **Vocabulary discipline**: all UI labels/headers/status text use backfill, frontier, poll, fully
  synced, enrichment, activity, stream, segment effort, athlete; proscribed synonyms are not used.

### II. Testing Standards (NON-NEGOTIABLE) — PASS (plan mandates it)
- Each user-story slice ships tests mapping to its acceptance criteria.
- No live Strava calls (the dashboard has none); tests run offline against fixture databases.
- DB/query tests use a real temp SQLite file in WAL mode (schema + `json_extract`/`strftime` paths
  exercised as in production).
- Pure-reader guard test added for the dashboard module (mirrors the MCP guard, T066).
- Regression-first on any bug found during implementation.

### III. User Experience Consistency — PASS (adapted to the human surface)
- The MCP UX principle governs the *agent* tool surface; the dashboard is a distinct *human* surface,
  but the load-bearing rules carry over:
  - **Partial data is never exposed**: only activities with `enriched_at IS NOT NULL` appear in any
    view (reuses the existing visibility-aware reads).
  - **Honest empty/degraded states** instead of fabricated or partial output (empty mirror, no streams,
    worker not running).
  - **Actionable failures**: DB missing/unreadable and port-in-use exit with concrete instructions, not
    a stack trace (mirrors the `run uv run strava-mcp auth` pattern).

### IV. Performance & Rate-Limit Discipline — PASS
- **Rate limits N/A**: no API calls originate from the dashboard.
- **Single writer, concurrent readers**: read-only connections (`mode=ro`) per request under WAL; the
  dashboard never takes a write lock and never blocks the worker (SC-005).
- **Queries are cheap**: filters hit indexed promoted columns (`start_date_epoch`, `sport_type`);
  timeline aggregates are computed in SQL (`strftime` group-by), not in Python; pagination via
  `LIMIT/OFFSET`.
- **Streams stored efficiently / read once**: the detail view reads the single `activity_streams` row
  and **downsamples** in Python before emitting SVG, so chart size is bounded regardless of activity
  length.

### Technology & Security Constraints — PASS
- Python 3.11+, `uv`; new entrypoint `uv run strava-mcp dashboard`.
- Loopback bind mandatory (`DASHBOARD_HOST=127.0.0.1`); no auth layer (single-user loopback), matching
  the `serve` posture.
- No write OAuth scopes involved (the dashboard touches no tokens for API use; it must not render any
  token/secret).
- No new runtime dependency; no external network at runtime (no CDN assets, no map tiles).
- Logging reuses the rotating file logger; logs contain no secrets.

**Result**: All gates pass. **No entries in Complexity Tracking.**

## Project Structure

### Documentation (this feature)

```text
specs/002-dashboard/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output — resolved tech decisions
├── data-model.md        # Phase 1 output — read-projection view models
├── quickstart.md        # Phase 1 output — run & validation guide
├── contracts/
│   ├── cli.md           # `dashboard` subcommand contract
│   └── http-routes.md   # Dashboard URL routes (the UI's interface contract)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
strava_mcp/
├── __main__.py                 # + `dashboard` subcommand (lazy import, like `serve`)
├── config.py                   # + dashboard_host / dashboard_port settings
├── dashboard/                  # NEW pure-reader module (sibling to mcp/)
│   ├── __init__.py
│   ├── server.py               # ThreadingHTTPServer + request router + run_dashboard()
│   ├── handlers.py             # route → (read via queries) → render HTML
│   ├── queries.py              # read-only composition over repositories/ (no ad-hoc SQL in handlers)
│   ├── views.py                # view-model builders (data-model.md projections)
│   ├── render.py               # HTML page/templating helpers (escaped)
│   ├── charts.py               # stream → inline SVG line charts (+ downsampling)
│   └── static/
│       └── app.css             # single bundled stylesheet (served locally, no CDN)
├── db/
│   ├── repositories/
│   │   ├── activities.py       # + paginated list_page(...)+count, training_rollup(period), efforts_for_activity(id)
│   │   └── segments.py         # (efforts_for_segment exists; add efforts_for_activity if homed here)
│   └── ...
└── mcp/                        # unchanged (summarize_training may delegate to the shared rollup)

tests/
├── dashboard/
│   ├── test_cli_dashboard.py         # subcommand wiring, port-in-use & missing-DB messages
│   ├── test_queries.py               # list/pagination/filters/timeline/efforts/sync read correctness
│   ├── test_handlers.py              # routes return expected HTML / states (fixture DB)
│   ├── test_charts.py                # SVG generation + downsampling bounds, absent-stream handling
│   └── test_pure_reader_guard.py     # asserts no import of client/sync
└── ...
```

**Structure Decision**: Single project. Add a new `strava_mcp/dashboard/` package as a sibling
pure-reader surface to `strava_mcp/mcp/`, and a `dashboard` CLI subcommand. All database access flows
through the existing `repositories/` layer (extended with a small number of read methods), preserving
the constitution's typed-boundary and module-separation rules. No schema change; no new dependency.

## Complexity Tracking

> No constitution violations — this section is intentionally empty.
