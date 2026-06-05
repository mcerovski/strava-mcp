---
description: "Task list for Strava MCP Local Mirror implementation"
---

# Tasks: Strava MCP Local Mirror

**Input**: Design documents from `/specs/001-strava-mcp-mirror/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: INCLUDED — the project constitution (Principle II, NON-NEGOTIABLE) requires every
slice to ship with tests covering its acceptance criteria, with no live Strava calls. Test
tasks are therefore mandatory here, not optional.

**Organization**: Tasks are grouped by user story (US1–US8 from spec.md, matching PLAN.md
slices 1–8). User stories in this feature are **layered**, not fully independent — the
dependency shape from PLAN.md is `1 → 2 → 3 → { 4 → { 5, 6 }, 7, 8 }`. Each story is still
independently *testable* at its checkpoint.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US8 (user-story phases only)
- Paths are repo-root relative; layout per plan.md.

## Path Conventions

Single Python project: package `strava_mcp/`, tests under `tests/` at repo root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and tooling.

- [X] T001 Initialize `uv` project: create `pyproject.toml` (project name `strava-mcp`, Python 3.11+, deps `fastmcp`, `httpx`, `pydantic-settings`; dev deps `pytest`, `ruff`, `mypy`) and the empty `strava_mcp/` package tree (`strava_mcp/__init__.py`, `auth/`, `client/`, `db/`, `db/repositories/`, `sync/`, `sync/resources/`, `mcp/`, `mcp/tools/` with `__init__.py` each), then run `uv sync`.
- [X] T002 [P] Configure `ruff` (lint + format) and `mypy` (strict on `strava_mcp`) sections in `pyproject.toml`.
- [X] T003 [P] Create test scaffolding: `tests/conftest.py` with a temp-SQLite-in-WAL fixture and an injectable clock fixture, plus an empty `tests/fixtures/` dir and a fixture-loader helper `tests/fixtures/__init__.py`.
- [X] T004 [P] Generate recorded API fixtures under `tests/fixtures/` (athlete, athlete_zones, athlete_stats, activity_summary, activity_detail, laps, comments, kudos, zones, streams, gear, route, segment, segment_effort) shaped to `strava-api-spec/swagger/*.json`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure every user story depends on.

**⚠️ CRITICAL**: No user-story work begins until this phase is complete.

- [X] T005 Implement `strava_mcp/config.py` — `pydantic-settings` loader for env/`.env` (client creds, scopes, redirect host/port, DB path, MCP host/port, `SYNC_MAX_REQUESTS`) with defaults matching `.env.example`.
- [X] T006 Write `strava_mcp/db/schema.sql` — full DDL from data-model.md: `raw_responses` (append-only) + `tokens`, `athlete`, `activities` (incl. `enriched_at`), `activity_streams`, `laps`, `comments`, `kudos`, `activity_zones`, `segment_efforts`, `segments`, `gear`, `routes`, `sync_state`, plus all indexes.
- [X] T007 Implement `strava_mcp/db/engine.py` — connection factory (WAL pragma), schema apply/bootstrap on first open, read-only connection helper for tools.
- [X] T008 [P] Implement `strava_mcp/db/repositories/__init__.py` — base repository helpers + the **dual-write** primitive (write `raw_responses` row + normalized row in one call).
- [X] T009 [P] Implement `strava_mcp/logging.py` — dual sink (`StreamHandler` stdout + `RotatingFileHandler` `./.database/strava-mcp.log`) with a secret-redaction filter.
- [X] T010 Implement `strava_mcp/client/http.py` — thin Strava client (base URL, bearer header, JSON decode, error/`Fault` mapping). Token refresh & rate limiting added in later stories.

**Checkpoint**: Foundation ready — user stories can begin in dependency order.

---

## Phase 3: User Story 1 - Authorize the mirror once (Priority: P1) 🎯 First slice

**Goal**: Complete the full-scope OAuth flow and persist refreshable tokens in the DB.

**Independent Test**: `uv run strava-mcp auth` opens consent for the full scopes, auto-captures the code, persists tokens, and a probe read `GET /athlete/activities?per_page=1` returns 200.

### Tests for User Story 1 ⚠️ (write first, ensure they fail)

- [X] T011 [P] [US1] Contract test for the `auth` CLI flow (authorize URL build, callback capture, token persistence, scope report) in `tests/contract/test_cli_auth.py`.
- [X] T012 [P] [US1] Unit test token storage, `.env`-override precedence, and near-expiry auto-refresh in `tests/unit/test_tokens.py`.

### Implementation for User Story 1

- [X] T013 [US1] Implement `strava_mcp/auth/tokens.py` — persist/read the single `tokens` row, DB-over-`.env` precedence, and refresh via `POST /oauth/token` (`grant_type=refresh_token`), persisting the returned (possibly rotated) refresh token.
- [X] T014 [US1] Implement `strava_mcp/auth/oauth.py` — build the authorize URL from `STRAVA_SCOPES` + `state`, run the one-shot `127.0.0.1:${OAUTH_REDIRECT_PORT}` callback to auto-capture `code`/`scope`, and exchange the code for tokens.
- [X] T015 [US1] Implement `strava_mcp/__main__.py` `auth` command — browser open (`webbrowser`) with headless URL-print fallback, persist tokens, verify with `GET /athlete/activities?per_page=1`, report granted scopes; non-zero exit on denial/failure.
- [X] T016 [US1] Add the required-scope set + a scope-sufficiency check helper in `strava_mcp/auth/__init__.py` (reused by `serve`), warning when the granted scope is narrower than requested.

**Checkpoint**: Tokens mintable and refreshable; US1 testable standalone.

---

## Phase 4: User Story 2 - Serve the athlete profile to an agent (Priority: P1)

**Goal**: `serve` boots (scope-check-or-exit), runs the MCP server + worker, BOOTSTRAP mirrors the athlete, and `get_athlete` returns it from the DB.

**Independent Test**: With a valid token, `serve` starts on loopback; `get_athlete()` returns profile/zones/stats from the DB. With an under-scoped token, `serve` exits printing `run uv run strava-mcp auth`.

**Depends on**: US1.

### Tests for User Story 2 ⚠️

- [X] T017 [P] [US2] Contract test: `serve` scope-check-or-exit + `get_athlete` pure-read in `tests/contract/test_serve_athlete.py`.
- [X] T018 [P] [US2] Integration test: BOOTSTRAP fetches athlete profile+zones+stats and dual-writes (raw + normalized) in `tests/integration/test_bootstrap_athlete.py`.

### Implementation for User Story 2

- [X] T019 [US2] Extend `strava_mcp/client/http.py` with automatic token refresh (near-expiry) using `auth/tokens.py`.
- [X] T020 [P] [US2] Implement `strava_mcp/db/repositories/athlete.py` — write/read the single `athlete` row (detail/zones/stats + dual-write).
- [X] T021 [P] [US2] Implement `strava_mcp/sync/resources/athlete.py` — fetch `/athlete`, `/athlete/zones`, `/athletes/{id}/stats` and dual-write via the repo.
- [X] T022 [US2] Implement `strava_mcp/sync/orchestrator.py` — worker-thread skeleton + BOOTSTRAP phase (athlete only for now) writing `sync_state.phase`.
- [X] T023 [US2] Implement `strava_mcp/mcp/server.py` — FastMCP `streamable-http` app bound to `MCP_HOST:MCP_PORT` (loopback), scope-check-or-exit on boot, owns/starts the worker thread, registers tools.
- [X] T024 [US2] Wire `strava_mcp/__main__.py` `serve` command to `mcp/server.py`.
- [X] T025 [P] [US2] Implement `strava_mcp/mcp/tools/athlete.py` — `get_athlete()` pure DB read (incl. `not_yet_synced` empty state).

**Checkpoint**: End-to-end path proven on one resource; agent can read the athlete.

---

## Phase 5: User Story 3 - Browse and query the activity history (Priority: P1)

**Goal**: Newest→oldest backfill of activity summaries with the rate limiter, checkpoint/resume, `list_activities`/`get_activity`, and `sync_status`.

**Independent Test**: Activities appear newest-first; date/sport filters return the right subset; restart mid-backfill resumes with zero re-fetch; budget exhaustion triggers deterministic cooldown; `sync_status` reports frontier/%/counts/budget/cooldown.

**Depends on**: US2.

### Tests for User Story 3 ⚠️

- [X] T026 [P] [US3] Unit test rate-limit header parsing + deterministic cooldown-to-next-reset math (quarter-hour/midnight UTC, injectable clock) in `tests/unit/test_ratelimit.py`.
- [X] T027 [P] [US3] Integration test backfill paging newest→oldest, per-page checkpoint, and restart-resume with no re-fetch in `tests/integration/test_backfill.py`.
- [X] T028 [P] [US3] Contract test `list_activities` (date/sport filters), `get_activity` (summary), `sync_status` in `tests/contract/test_activities_tools.py`.

### Implementation for User Story 3

- [X] T029 [P] [US3] Implement `strava_mcp/client/ratelimit.py` — parse `X-ReadRateLimit-*`/`X-RateLimit-*`, track budget, compute cooldown to known next reset, 429 backoff; integrate into `client/http.py`.
- [X] T030 [P] [US3] Implement `strava_mcp/sync/state.py` — `sync_state` access: `backfill_frontier_epoch`, `newest_synced_epoch`, phase, cooldown, rate-limit snapshot, run log; checkpoint API.
- [X] T031 [P] [US3] Implement `strava_mcp/db/repositories/activities.py` — summary insert, visibility-aware reads (`enriched_at IS NOT NULL`), date-range + `sport_type` filters on promoted columns.
- [X] T032 [US3] Implement `strava_mcp/sync/resources/activities.py` — page `/athlete/activities` newest→oldest, dual-write summaries, advance frontier.
- [X] T033 [US3] Extend `strava_mcp/sync/orchestrator.py` — BACKFILL phase + COOLDOWN integration + per-page checkpoint; resume from frontier on restart.
- [X] T034 [P] [US3] Implement `strava_mcp/mcp/tools/activities.py` — `list_activities(after?, before?, sport_type?, limit?)` and `get_activity(id)` (summary; `not_yet_synced` when unenriched).
- [X] T035 [P] [US3] Implement `strava_mcp/mcp/tools/sync.py` — `sync_status()` (frontier date, % complete, fully-synced flag, counts, rate-limit budget, cooldown ETA).

**Checkpoint**: 🎯 **Useful agent-facing MVP** — auth → serve → queryable, self-throttling, resumable activity history.

---

## Phase 6: User Story 4 - Read full per-activity detail (Priority: P2)

**Goal**: Single-unit enrichment (detail + laps + comments + kudos + zones + embedded segment efforts **+ streams**), visibility flag stamped last, and the per-facet tools.

> **Visibility invariant (data-model R8, Constitution III):** "fully enriched" **includes streams**. The enrichment transaction therefore writes streams too, and `enriched_at` is stamped **only after streams are persisted**. US4 owns the *enrichment write path incl. streams*; US5 (Phase 7) adds the streams *read surface, key-filtering, and the fully-synced flag*. This keeps every shippable state free of stream-less visible activities.

**Independent Test**: An enriched activity (streams present) exposes full detail + each facet and its efforts; an activity not yet fully enriched (incl. streams) returns `not_yet_synced`; no partial activity is ever visible.

**Depends on**: US3.

### Tests for User Story 4 ⚠️

- [X] T036 [P] [US4] Integration test single-transaction enrichment **including streams** + `enriched_at` stamped last (no partial exposure; an activity missing streams stays `not_yet_synced`) + efforts populated from embedded data, in `tests/integration/test_enrichment.py`.
- [X] T037 [P] [US4] Contract test `get_laps`/`get_comments`/`get_kudos`/`get_activity_zones` and full `get_activity` in `tests/contract/test_enrichment_tools.py`.

### Implementation for User Story 4

- [X] T038 [P] [US4] Extend `strava_mcp/db/repositories/activities.py` with writers for `laps`, `comments`, `kudos`, `activity_zones`, and `segment_efforts`, and add `strava_mcp/db/repositories/streams.py` (write the `activity_streams` row) — all dual-write.
- [X] T039 [US4] Extend `strava_mcp/sync/resources/activities.py` — enrichment unit: fetch `DetailedActivity` + laps + comments + kudos + zones + **streams** (`/activities/{id}/streams?keys=...&key_by_type=true`), populate `segment_efforts` from embedded `segment_efforts[]`/`best_efforts[]`, write all (including the `activity_streams` row) in one transaction, and stamp `enriched_at` **last, only after streams are stored**.
- [X] T040 [US4] Extend `strava_mcp/mcp/tools/activities.py` — `get_activity` returns full `DetailedActivity`; add `get_laps`/`get_comments`/`get_kudos`/`get_activity_zones` (each `not_yet_synced`-aware).

**Checkpoint**: Activities visible only when fully enriched **including streams**; deep per-activity reads work.

---

## Phase 7: User Story 5 - Access activity streams (Priority: P2)

**Goal**: Expose the streams stored by the US4 enrichment unit to agents (with key-filtering) and finalize the **fully-synced** definition. (Streams are *written* in US4 so the visibility invariant holds; US5 owns the *read surface* + fully-synced flag.)

**Independent Test**: An enriched activity returns requested stream types with metadata; an activity not fully enriched returns `not_yet_synced`; `fully_synced` flips true only once all activities carry streams and the frontier reached the first-ever activity.

**Depends on**: US4.

### Tests for User Story 5 ⚠️

- [X] T041 [P] [US5] Integration test streams retrievable per type + `fully_synced` condition flips only after all activities carry streams, in `tests/integration/test_streams.py`.
- [X] T042 [P] [US5] Contract test `get_activity_streams(id, keys?)` incl. key-filtering and `not_yet_synced` in `tests/contract/test_streams_tool.py`.

### Implementation for User Story 5

- [X] T043 [P] [US5] Extend `strava_mcp/db/repositories/streams.py` (created in US4/T038) with read + **key-filtering** (return only requested stream types) and `types` metadata.
- [X] T044 [P] [US5] Implement `strava_mcp/mcp/tools/streams.py` — `get_activity_streams(id, keys?)` (`not_yet_synced`-aware).
- [X] T045 [US5] Extend `strava_mcp/sync/state.py` — `fully_synced` = backfill_complete AND every activity has streams; surface it in `sync_status`.
- [X] T046 [P] [US5] Regression guard: assert the enrichment transaction (US4) always persists an `activity_streams` row before stamping `enriched_at`, in `tests/integration/test_enrichment_streams_invariant.py`.

**Checkpoint**: "Fully synced" definition complete; stream reads + key-filtering work.

---

## Phase 8: User Story 6 - Read gear, routes, and starred segments (Priority: P2)

**Goal**: BOOTSTRAP rounded out with gear, routes (metadata + polyline), and starred segments (full detail); encountered segments kept as embedded summaries; their tools.

**Independent Test**: Gear/routes/starred segments listable+readable; `get_segment` returns detail for starred, embedded summary for encountered (no extra fetch); `list_segment_efforts` returns efforts.

**Depends on**: US4 (for encountered-segment efforts source).

### Tests for User Story 6 ⚠️

- [X] T047 [P] [US6] Integration test BOOTSTRAP gear/routes/starred dual-write + starred-not-downgraded precedence in `tests/integration/test_bootstrap_resources.py`.
- [X] T048 [P] [US6] Contract test gear/routes/segments tools (incl. starred-vs-encountered, no live fetch) in `tests/contract/test_resources_tools.py`.

### Implementation for User Story 6

- [X] T049 [P] [US6] Implement `strava_mcp/db/repositories/gear.py`.
- [X] T050 [P] [US6] Implement `strava_mcp/db/repositories/routes.py`.
- [X] T051 [P] [US6] Implement `strava_mcp/db/repositories/segments.py` — starred upsert (full detail), encountered insert from efforts, starred-precedence rule.
- [X] T052 [P] [US6] Implement `strava_mcp/sync/resources/gear.py` (ids from `athlete.bikes`/`shoes` → `/gear/{id}`).
- [X] T053 [P] [US6] Implement `strava_mcp/sync/resources/routes.py` (`/athletes/{id}/routes` + `/routes/{id}`, metadata + polyline only).
- [X] T054 [P] [US6] Implement `strava_mcp/sync/resources/segments.py` (`/segments/starred` full; encountered from enrichment efforts).
- [X] T055 [US6] Extend `strava_mcp/sync/orchestrator.py` BOOTSTRAP to run gear + routes + starred segments.
- [X] T056 [P] [US6] Implement `strava_mcp/mcp/tools/gear.py` — `list_gear`/`get_gear`.
- [X] T057 [P] [US6] Implement `strava_mcp/mcp/tools/routes.py` — `list_routes`/`get_route`.
- [X] T058 [P] [US6] Implement `strava_mcp/mcp/tools/segments.py` — `list_starred_segments`/`get_segment`/`list_segment_efforts`.

**Checkpoint**: Athlete's full world (gear/routes/segments) mirrored and served.

---

## Phase 9: User Story 7 - Stay current with new activities (Priority: P3)

**Goal**: Steady-state POLL (12h, 14-day lookback, dedupe-by-id, insert-only) + `sync_now` nudge.

**Independent Test**: On a fully-synced mirror, `sync_now` runs the POLL; a new and a back-dated-within-window activity are enriched+inserted; existing rows untouched.

**Depends on**: US3 (cursors/backfill) — enrichment reuse from US4/US5.

### Tests for User Story 7 ⚠️

- [X] T059 [P] [US7] Integration test POLL lookback + dedupe-by-id + insert-only + back-dated capture in `tests/integration/test_poll.py`.
- [X] T060 [P] [US7] Contract test `sync_now` (triggers poll, reports outcome, no mutation) in `tests/contract/test_sync_now.py`.

### Implementation for User Story 7

- [X] T061 [US7] Extend `strava_mcp/sync/orchestrator.py` — POLL phase: every 12h list `after = newest_synced − 14d`, dedupe by id, enrich+insert unseen only, advance `newest_synced_epoch`; never mutate existing rows.
- [X] T062 [US7] Extend `strava_mcp/mcp/tools/sync.py` — `sync_now()` nudges an immediate POLL and reports the outcome.

**Checkpoint**: Mirror stays current after backfill.

---

## Phase 10: User Story 8 - Summarize training at a glance (Priority: P3)

**Goal**: SQL-computed `summarize_training` rollups + README.

**Independent Test**: `summarize_training(period, sport_type?)` rollups match the underlying activities.

**Depends on**: US3.

### Tests for User Story 8 ⚠️

- [X] T063 [P] [US8] Contract test `summarize_training` weekly/monthly + sport filter correctness in `tests/contract/test_summaries.py`.

### Implementation for User Story 8

- [X] T064 [P] [US8] Implement `strava_mcp/mcp/tools/summaries.py` — `summarize_training(period, sport_type?)` computing counts/distance/time/elevation in SQL over enriched activities.
- [X] T065 [US8] Write `README.md` — `.env` setup, `uv run strava-mcp auth`, `uv run strava-mcp serve`, connecting an MCP client, plus the rate-limit reality (backfill may take days) and read-only/insert-only scope.

**Checkpoint**: All user stories functional; project documented.

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: Enforce the constitution's invariants and validate end-to-end.

- [X] T066 [P] Pure-reader guard test: assert no module under `strava_mcp/mcp/tools/` imports `strava_mcp.client` or `strava_mcp.sync`, in `tests/contract/test_pure_reader.py`.
- [X] T067 [P] Dual-write invariant test across all repositories (every normalized write has a matching `raw_responses` row) in `tests/integration/test_dual_write.py`.
- [X] T068 [P] Vocabulary-discipline check: scan `strava_mcp/` for banned synonyms (import/refresh/cache/etc. per CONTEXT.md) in `tests/unit/test_vocabulary.py`.
- [X] T069 Run all `quickstart.md` scenarios end-to-end against fixtures and record results.
- [X] T070 [P] Final `uv run ruff check .` + `uv run mypy strava_mcp` clean; cross-link ADRs 0001–0003 from code docstrings where relevant.

### Remediation coverage (added from `/speckit-analyze`)

> These close coverage gaps flagged in the analysis. IDs are sequential at end-of-file, but each is tagged with the story/phase it should actually be executed within.

- [X] T071 [P] [US3] Integration test: backfill **termination** when the frontier reaches the first-ever activity, and the **empty-account** case → `backfill_complete` flips correctly, in `tests/integration/test_backfill_complete.py`. *(Run during US3; closes spec Edge Case "Empty account / first-ever activity".)*
- [X] T072 [P] Unit test: log **redaction** never emits token-like secrets to stdout or the rotating file, in `tests/unit/test_log_redaction.py`. *(Closes SC-010 / FR-023; pair with T009.)*
- [X] T073 [P] Integration test: a tool **read succeeds concurrently** with the worker writing under WAL (no blocking either way), in `tests/integration/test_concurrent_read.py`. *(Closes spec Edge Case "Concurrent agent reads during backfill".)*
- [X] T074 [P] Contract test: **multiple MCP clients** connect and the server persists across simulated sessions, in `tests/contract/test_multi_client.py`. *(Closes FR-007.)*

---

## Dependencies & Execution Order

### Phase / story dependency graph (from PLAN.md `1 → 2 → 3 → { 4 → { 5, 6 }, 7, 8 }`)

```text
Setup (P1) → Foundational (P2) → US1 → US2 → US3 ─┬─ US4 ─┬─ US5
                                                  │       └─ US6
                                                  ├─ US7
                                                  └─ US8
                                            → Polish (P11)
```

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: after Setup; blocks all stories.
- **US1**: after Foundational.
- **US2**: after US1. **US3**: after US2.
- **US4**: after US3. **US7**: after US3. **US8**: after US3.
- **US5**: after US4. **US6**: after US4.
- **Polish (Phase 11)**: after all targeted stories.

### Within each story

- Tests first (must fail), then repositories/models → syncers/services → tools, then integration.

### Parallel opportunities

- Setup: T002, T003, T004 in parallel after T001.
- Foundational: T008, T009 in parallel (T010 after; T006→T007 sequential).
- Per story, all `[P]` tests run together, and `[P]` repositories/tools across different files run together.
- After US3, the branches **US4**, **US7**, **US8** can proceed in parallel (different files); **US5** and **US6** parallelize after US4.

---

## Parallel Example: User Story 3

```bash
# Tests for US3 together:
Task: "Unit test rate-limit cooldown in tests/unit/test_ratelimit.py"          # T026
Task: "Integration test backfill resume in tests/integration/test_backfill.py" # T027
Task: "Contract test activity tools in tests/contract/test_activities_tools.py" # T028

# Then parallel implementation across distinct files:
Task: "client/ratelimit.py"         # T029
Task: "sync/state.py"               # T030
Task: "db/repositories/activities.py" # T031
# (T032, T033 sequential — same orchestrator/resource files; T034, T035 parallel tools)
```

---

## Implementation Strategy

### MVP scope

- **Smallest independently-testable slice**: **US1** (authorize → refreshable tokens).
- **Smallest *agent-facing* MVP**: **US1 + US2 + US3** — authorize, serve, and a queryable,
  self-throttling, resumable activity history (Phase 5 checkpoint 🎯). This is the first point
  an agent gets real value.

### Incremental delivery

1. Setup + Foundational → foundation ready.
2. US1 → US2 → US3 → demo the agent-facing MVP.
3. US4 → US5 / US6 → richer per-activity data and the athlete's world.
4. US7 (stay current) and US8 (summaries) → steady state + convenience.
5. Polish → enforce invariants, validate quickstart.

### Notes

- `[P]` = different files, no incomplete dependencies.
- Tests are mandatory (Constitution II): no live Strava calls; DB tests use real temp SQLite (WAL).
- Honor the architectural invariant throughout: **MCP tools never call Strava** — only the worker does.
- Commit after each task or logical group; stop at any checkpoint to validate the story.
