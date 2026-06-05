---

description: "Task list for Local Data Dashboard"
---

# Tasks: Local Data Dashboard

**Input**: Design documents from `/specs/002-dashboard/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (cli.md, http-routes.md), quickstart.md

**Tests**: REQUIRED. The project constitution (II. Testing Standards — NON-NEGOTIABLE) requires every
slice to ship with tests mapping to its acceptance criteria, run offline against real temp SQLite
fixtures in WAL mode. No live Strava calls (the dashboard has none).

**Organization**: Tasks are grouped by user story (P1→P4) so each is independently implementable and
testable. The dashboard is a pure-reader sibling to `strava_mcp/mcp/` — no schema changes, no new
dependency, no writes, no Strava calls.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US4 (Setup/Foundational/Polish have no story label)

## Path Conventions

Single project. New module at `strava_mcp/dashboard/`; tests at `tests/dashboard/`; repository
extensions in existing `strava_mcp/db/repositories/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the module skeleton and configuration the rest of the work hangs off.

- [X] T001 Create the dashboard package skeleton: `strava_mcp/dashboard/__init__.py` (module docstring stating the pure-reader boundary — MUST NOT import `strava_mcp.client` or `strava_mcp.sync`, MUST NOT write the DB) and the empty `strava_mcp/dashboard/static/` directory.
- [X] T002 [P] Add `dashboard_host` (default `127.0.0.1`) and `dashboard_port` (default `8722`) settings to `strava_mcp/config.py`.
- [X] T003 [P] Add the bundled stylesheet `strava_mcp/dashboard/static/app.css` (local-only, no CDN references).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The serving/render/query plumbing and CLI entrypoint every route depends on.

**⚠️ CRITICAL**: No user-story route can be implemented until this phase is complete.

- [X] T004 Implement HTML shell + formatting helpers in `strava_mcp/dashboard/render.py`: page layout (nav links to `/`, `/timeline`, `/sync`), the `/static/app.css` link, `html.escape` discipline for all dynamic text, and value formatters (distance, h:mm:ss duration, dates) using the fixed vocabulary.
- [X] T005 Implement the HTTP server in `strava_mcp/dashboard/server.py`: `ThreadingHTTPServer` bound to `dashboard_host:dashboard_port`, a request router dispatching to `handlers.py`, serving `GET /static/app.css` (`text/css`) from the bundled stylesheet, a per-request read-only connection via `engine.read_only_connect`, a `404` HTML handler for unknown paths, and `run_dashboard()` with actionable failures — missing/unreadable DB → `No mirror found at <path>. Run 'uv run strava-mcp serve' first ...` (exit 1); port in use (`OSError`) → `Port <n> is in use. Set DASHBOARD_PORT to a free port and retry.` (exit 1); print the bind URL on success.
- [X] T006 Wire the `dashboard` subcommand into `strava_mcp/__main__.py` (`build_parser` + `_cmd_dashboard` that lazily imports `strava_mcp.dashboard.server.run_dashboard`, mirroring `_cmd_serve`).
- [X] T007 Create `strava_mcp/dashboard/queries.py` (read-only composition entry point over the `repositories/` layer — no ad-hoc SQL in handlers) and `strava_mcp/dashboard/handlers.py` (route→query→render dispatch skeleton) and `strava_mcp/dashboard/views.py` (view-model builder skeleton).
- [X] T008 Implement the shared athlete header (FR-018) in `strava_mcp/dashboard/views.py` + `render.py` using `AthleteRepository.read()`, with a neutral placeholder when no athlete row exists (empty mirror).
- [X] T009 [P] Add the pure-reader guard test in `tests/dashboard/test_pure_reader_guard.py` asserting `strava_mcp.dashboard` (and submodules) import neither `strava_mcp.client` nor `strava_mcp.sync`.
- [X] T010 [P] Add `tests/dashboard/test_cli_dashboard.py`: `dashboard` subcommand is registered/dispatched, and the missing-DB and port-in-use paths produce the documented messages and exit code (no stack trace).

**Checkpoint**: `uv run strava-mcp dashboard` starts, serves the shell + athlete header, and fails gracefully on missing DB / busy port. User stories can now begin.

---

## Phase 3: User Story 1 - Browse all mirrored activities in a list (Priority: P1) 🎯 MVP

**Goal**: A filterable, paginated, newest-first list of enriched-only activities on `/`.

**Independent Test**: With a populated fixture mirror, `GET /` shows all enriched activities newest-first with summary fields; `?sport_type=` and `?after=/?before=` narrow the list and update the count; an empty mirror shows an empty state; a listed-but-not-enriched activity never appears.

### Tests for User Story 1 ⚠️ (write first, ensure they fail)

- [X] T011 [P] [US1] Test list reads in `tests/dashboard/test_queries.py`: pagination (limit/offset), sport-type and date-range filters, newest-first order, enriched-only visibility, and total count correctness against a real temp SQLite fixture.
- [X] T012 [P] [US1] Test the `/` route in `tests/dashboard/test_handlers.py`: rendered rows match stored enriched activities, active filters + result count shown, prev/next paging links, and the empty-mirror empty state.

### Implementation for User Story 1

- [X] T013 [US1] Add `list_page(*, after_epoch, before_epoch, sport_type, limit, offset)` and `count_enriched(*, after_epoch, before_epoch, sport_type)` (visibility-aware, indexed filters) to `strava_mcp/db/repositories/activities.py`.
- [X] T014 [US1] Implement `list_activities_page(...)` in `strava_mcp/dashboard/queries.py` composing the repository calls (rows + total count).
- [X] T015 [US1] Implement the `ActivityListItem` view builder in `strava_mcp/dashboard/views.py` and the list-page render (table rows, filter controls, count, pager) in `strava_mcp/dashboard/render.py`.
- [X] T016 [US1] Implement the `GET /` route in `strava_mcp/dashboard/handlers.py`: parse `sport_type`/`after`/`before`/`page`, render the athlete header + list + pager + empty state.

**Checkpoint**: `/` is a fully functional, filterable, paginated activity list — the MVP.

---

## Phase 4: User Story 2 - Open one activity and view its data graphs (Priority: P2)

**Goal**: `/activity/{id}` shows summary + laps + segment efforts + HR/power zones + inline-SVG stream graphs.

**Independent Test**: For an enriched fixture activity with streams, the detail page renders one graph per present stream type and the summary/laps/efforts/zones match stored values; an activity without streams shows a "no stream data" note; a missing/not-yet-enriched id returns a 404 not-found page.

### Tests for User Story 2 ⚠️ (write first, ensure they fail)

- [X] T017 [P] [US2] Test chart generation in `tests/dashboard/test_charts.py`: inline-SVG produced per present stream type, downsampling keeps point count within the bound, and absent stream types yield no chart (never a faked/empty graph).
- [X] T018 [P] [US2] Test the `/activity/{id}` route in `tests/dashboard/test_handlers.py`: summary/laps/segment-efforts/zones match the fixture, no-stream "no stream data" note, and a missing/not-yet-enriched id returns the 404 not-found page.

### Implementation for User Story 2

- [X] T019 [P] [US2] Add `efforts_for_activity(activity_id)` (read, visibility-agnostic but only reached for enriched activities) to `strava_mcp/db/repositories/segments.py`.
- [X] T020 [US2] Implement `strava_mcp/dashboard/charts.py`: stream downsampling (target ≈800–1200 points) and per-type inline-SVG line charts (x = time or distance) with axis labels/units.
- [X] T021 [US2] Implement the `ActivityDetailView` builder in `strava_mcp/dashboard/views.py` and `activity_detail(id)` in `queries.py` composing `get_detail`, `laps`, `zones`, `efforts_for_activity`, and `StreamsRepository.read`.
- [X] T022 [US2] Implement the detail-page render in `strava_mcp/dashboard/render.py` (summary, laps, segment efforts, zone distribution, graphs; omit empty sections) and the `GET /activity/{id}` route in `handlers.py` (incl. 404 / not-yet-enriched and the no-stream note).

**Checkpoint**: List → detail navigation works; graphs render from stored streams; kudos/comments correctly excluded.

---

## Phase 5: User Story 3 - See training over week, month, and year timelines (Priority: P3)

**Goal**: `/timeline` groups enriched activities into week/month/year buckets with aggregate totals.

**Independent Test**: With a multi-month fixture, `/timeline?period=week|month|year` recomputes buckets and totals server-side; bucket totals equal the SQL sum of matching enriched activities; empty periods appear as zero buckets so gaps stay visible.

### Tests for User Story 3 ⚠️ (write first, ensure they fail)

- [X] T023 [P] [US3] Test rollups in `tests/dashboard/test_queries.py`: `training_rollup` for weekly/monthly/yearly returns correct SQL aggregates, and the Python empty-bucket fill inserts zero buckets between first and last period.
- [X] T024 [P] [US3] Test the `/timeline` route in `tests/dashboard/test_handlers.py`: default monthly grouping, `?period=` switching, and zero buckets visible for empty periods.

### Implementation for User Story 3

- [X] T025 [US3] Add `training_rollup(period ∈ {weekly,monthly,yearly}, sport_type)` (adds the yearly `strftime('%Y-01-01', start_date)` bucket) to `strava_mcp/db/repositories/activities.py`, and refactor `summarize_training` in `strava_mcp/mcp/tools/summaries.py` to delegate to it (no duplicated SQL). **Regression (Constitution II):** the existing `summarize_training` tool output for `weekly`/`monthly` MUST remain byte-identical — run its existing tests and confirm they stay green before/after the refactor (add a yearly-period case only if the tool is to expose it; the dashboard's yearly path is covered by T023).
- [X] T026 [US3] Implement `timeline(period, sport_type)` in `strava_mcp/dashboard/queries.py` including the Python empty-bucket fill between the min and max returned period.
- [X] T027 [US3] Implement the timeline-page render (per-bucket count/distance/moving-time/elevation, period selector) in `strava_mcp/dashboard/render.py` and the `GET /timeline` route in `handlers.py`.

**Checkpoint**: Timeline view shows volume over week/month/year with visible training gaps.

---

## Phase 6: User Story 4 - Monitor sync progress (Priority: P4)

**Goal**: `/sync` shows current persisted sync state (phase, frontier, % complete, counts, rate budget, cooldown) at page load; manual reload reflects latest.

**Independent Test**: With a fixture `sync_state`, `/sync` reports the same phase/frontier/counts/rate-limit/cooldown; reloading after the figures change shows the new values; with no worker it shows the last persisted state; no auto-refresh occurs.

### Tests for User Story 4 ⚠️ (write first, ensure they fail)

- [X] T028 [P] [US4] Test the sync-progress read in `tests/dashboard/test_queries.py`: phase, frontier date, percent-complete, counts, fully-synced flag, rate-limit, and cooldown computed from a fixture `sync_state` + activity rows.
- [X] T029 [P] [US4] Test the `/sync` route in `tests/dashboard/test_handlers.py`: backfill-in-progress, cooldown, and fully-synced/polling states render correctly; page contains no auto-refresh mechanism.

### Implementation for User Story 4

- [X] T030 [US4] Implement `sync_progress()` in `strava_mcp/dashboard/queries.py` computing the same fields as the `sync_status` MCP tool (phase, frontier, percent, counts, fully_synced, rate_limit, cooldown, last_poll_at) over a read-only connection.
- [X] T031 [US4] Implement the sync-page render in `strava_mcp/dashboard/render.py` and the `GET /sync` route in `handlers.py` (current state on load; no background refresh).

**Checkpoint**: All four views are independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T032 Confirm no rendered page references any external/CDN asset — the only stylesheet is the locally-served `/static/app.css` (served in T005), charts are inline SVG, and there is no map (no-external-network posture).
- [X] T033 [P] Vocabulary + no-secrets audit across all rendered HTML in `strava_mcp/dashboard/` (fixed terms only; no token/secret ever emitted).
- [X] T034 [P] Update `README.md` (and add a short note to `docs/` if appropriate) documenting `uv run strava-mcp dashboard`, the default port, and the routes.
- [X] T035 Run `uv run ruff check strava_mcp/dashboard` and `uv run mypy strava_mcp` clean; ensure the full `uv run pytest -q` suite passes.
- [X] T036 Run the `quickstart.md` validation scenarios end-to-end against a populated mirror (US1–US4 + cross-cutting edge cases), confirming SC-001/002/003/004/005/006/007.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup; **blocks all user stories**.
- **User Stories (Phase 3–6)**: each depends only on Foundational; independent of each other (they touch
  different routes/render functions; the only shared edit point is `handlers.py`/`render.py` route
  additions, which are append-only per story).
- **Polish (Phase 7)**: depends on the desired stories being complete.

### User Story Dependencies

- **US1 (P1)**: after Foundational. No dependency on other stories. **MVP.**
- **US2 (P2)**: after Foundational. Uses the list only for navigation; independently testable via direct
  `/activity/{id}`.
- **US3 (P3)**: after Foundational. Independent.
- **US4 (P4)**: after Foundational. Independent.

### Within Each User Story

- Tests written first and failing → repository method → queries → views/render → route handler.
- `repositories/` edits precede the `queries.py` calls that use them.

### Parallel Opportunities

- Setup: T002, T003 in parallel.
- Foundational: T009, T010 (tests) in parallel; after T004–T008.
- Each story's two test tasks are [P] (different files); the repository-method task (e.g. T019) is [P]
  with that story's tests.
- With multiple developers, US1–US4 can proceed in parallel once Foundational is done (coordinate the
  shared `handlers.py`/`render.py` route additions).

---

## Parallel Example: User Story 1

```bash
# Tests first (different files, in parallel):
Task: "Test list reads in tests/dashboard/test_queries.py"          # T011
Task: "Test the / route in tests/dashboard/test_handlers.py"        # T012

# Then implementation in dependency order:
#   T013 (repositories/activities.py) → T014 (queries.py) → T015 (views.py+render.py) → T016 (handlers.py)
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & VALIDATE** (`/` list works,
   filters, pagination, empty state) → demo the MVP.

### Incremental Delivery

Foundation → US1 (MVP) → US2 (detail + graphs) → US3 (timeline) → US4 (sync progress) → Polish. Each
story adds value without breaking the previous ones.

---

## Notes

- [P] = different files, no incomplete dependencies. The dashboard adds **no schema/tables** and **no
  new dependency** — stdlib `http.server` + inline-SVG charts only.
- Every story ships with tests (Constitution II); verify they fail before implementing.
- Read-only WAL connections per request — never block the worker (SC-005); never expose a
  non-enriched activity (SC-006); never call Strava (SC-006).
- Commit after each task or logical group.
