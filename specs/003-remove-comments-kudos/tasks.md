---
description: "Task list for Remove Comments & Kudos for Faster Sync"
---

# Tasks: Remove Comments & Kudos for Faster Sync

**Input**: Design documents from `/specs/003-remove-comments-kudos/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: REQUIRED. Constitution Principle II (NON-NEGOTIABLE) mandates acceptance-criteria coverage and regression-first; all behavior changes ship with tests using real SQLite + offline fixtures.

**Organization**: Grouped by user story. US1 (faster sync) is the MVP; US2 (complete surface/data removal) and US3 (safe upgrade) build on it.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 (Setup, Foundational, Polish carry no story label)

## Path Conventions

Single project. Source under `strava_mcp/`, tests under `tests/`, governance/docs at repo root and `.specify/`.

---

## Phase 1: Setup

**Purpose**: Establish the regression baseline before any removal.

- [X] T001 Capture green baseline: run `uv run pytest` and confirm all tests pass; record the current per-activity Strava read-request count (6: detail + laps + comments + kudos + zones + streams) as the regression reference for SC-001.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Land the governed redefinition so all subsequent code/doc work is vocabulary-clean and review-passable.

**⚠️ CRITICAL**: The constitution currently hard-codes comments/kudos into the enrichment definition and declares the tool surface "stable"; amend it before removing them.

- [X] T002 Amend `.specify/memory/constitution.md` Principle III: redefine "fully enriched" as `detail + laps + zones + streams`; relax the "stable schemas" clause to permit this governed tool removal; bump version **1.0.0 → 2.0.0** (MAJOR — principle redefined) and update the SYNC IMPACT REPORT header with rationale.
- [X] T003 [P] Update canonical vocabulary in `CONTEXT.md`: remove "comments + kudos" from the enrichment-unit definition (lines ~34 and ~75) so the redefined unit (`detail + laps + zones + streams`) is the single source of truth.

**Checkpoint**: Governance redefined — removal work can proceed without violating vocabulary discipline.

---

## Phase 3: User Story 1 - Faster activity sync within the rate budget (Priority: P1) 🎯 MVP

**Goal**: Stop fetching comments and kudos during enrichment so each activity costs 4 read requests instead of 6, while activities still become visible once streams are stored.

**Independent Test**: Run the fixture-backed enrichment/backfill tests and confirm no `…/comments` or `…/kudos` request is issued per activity, the per-activity request count is 4, and the activity becomes visible after streams persist.

### Tests for User Story 1 (regression-first — write/adjust to FAIL before implementation)

- [X] T004 [P] [US1] Update `tests/integration/test_enrichment.py`: drop the comments(==2)/kudos(==3) write assertions and the fixture handler returning them; assert enrichment fetches only detail/laps/zones/streams (no comments/kudos calls).
- [X] T005 [P] [US1] Update `tests/integration/test_enrichment_streams_invariant.py`: change `repo.enrich(...)` calls to the new signature (remove `comments=`/`kudos=`); keep the streams-gated visibility assertion intact.
- [X] T006 [P] [US1] Update `tests/integration/test_dual_write.py`: remove "comments" and "kudos" from the facet/raw-write loops and endpoint-suffix checks so only remaining facets are asserted.
- [X] T029 [P] [US1] Assert rate/budget reporting reflects the reduced count (FR-013): in `tests/integration/test_enrichment.py` (or `test_backfill.py`), assert the per-activity request accounting / `sync_status` counters record exactly four requests per enriched activity (detail + laps + zones + streams) with no comments/kudos requests counted.

### Implementation for User Story 1

- [X] T007 [US1] In `strava_mcp/sync/resources/activities.py`, remove the two `_safe_list("/activities/{id}/comments")` and `_safe_list("/activities/{id}/kudos")` fetches in `enrich()` and drop `comments=`/`kudos=` from the `repo.enrich(...)` call.
- [X] T008 [US1] In `strava_mcp/db/repositories/activities.py`, remove the `comments`/`kudos` parameters from `enrich()`, drop the `_write_comments`/`_write_kudos` calls, and delete the `_write_comments` and `_write_kudos` methods (enrichment now writes detail + laps + zones + streams; `enriched_at` still stamped last after streams).

**Checkpoint**: Enrichment issues 4 requests/activity; US1 tests green. MVP delivers the rate-budget win.

---

## Phase 4: User Story 2 - No comments or kudos anywhere in the product (Priority: P2)

**Goal**: Remove the two MCP tools, the promoted count fields, the normalized tables/columns, and any display so nothing about comments/kudos remains in served surfaces or the data model.

**Independent Test**: List the tool surface (no `get_comments`/`get_kudos`), read an activity record (no `kudos_count`/`comment_count`), inspect the schema (no `comments`/`kudos` tables/columns), and audit the dashboard — all clear.

### Tests for User Story 2 (write/adjust to FAIL before implementation)

- [X] T009 [P] [US2] Update `tests/contract/test_multi_client.py`: assert `get_comments` and `get_kudos` are NOT in the registered tool set.
- [X] T010 [P] [US2] Update `tests/contract/test_enrichment_tools.py`: remove the `get_comments`/`get_kudos` assertions; keep `get_laps`/`get_activity_zones` coverage.
- [X] T011 [P] [US2] Update `tests/integration/test_quickstart.py`: remove `get_comments`/`get_kudos` imports and their length assertions.
- [X] T012 [P] [US2] Update `tests/integration/test_backfill.py`: remove `kudos_count`/`comment_count` from the activity fixture and any assertions on them.
- [X] T028 [P] [US2] Assert the removed capability fails as an unknown operation (FR-014): in `tests/contract/test_enrichment_tools.py` (or `test_multi_client.py`), assert that invoking `get_comments`/`get_kudos` against the server raises FastMCP's unknown-tool error rather than returning an empty or fabricated result.

### Implementation for User Story 2

- [X] T013 [P] [US2] Remove the `get_comments` and `get_kudos` functions from `strava_mcp/mcp/tools/activities.py` (leave `_facet`, `get_laps`, `get_activity_zones`).
- [X] T014 [US2] Remove the `get_comments` and `get_kudos` `@mcp.tool` registrations from `strava_mcp/mcp/server.py` (depends on T013).
- [X] T015 [US2] In `strava_mcp/db/repositories/activities.py`, remove `"kudos_count"`/`"comment_count"` from `_PROMOTED_KEYS` and from the `_summary_view()` returned dict, and delete the `comments()` and `kudos()` read methods.
- [X] T016 [US2] In `strava_mcp/db/schema.sql`, remove the `kudos_count`/`comment_count` columns from `activities` and delete the entire `comments` and `kudos` table+index definitions.
- [X] T017 [P] [US2] Audit `strava_mcp/dashboard/` (queries, views, templates, static) for any comments/kudos/`kudos_count`/`comment_count` reference; remove any incidental label. Confirm with a grep that returns nothing.

**Checkpoint**: Served surfaces and the fresh-DB schema contain zero comments/kudos; US1 + US2 tests green.

---

## Phase 5: User Story 3 - Safe upgrade of an already-running deployment (Priority: P3)

**Goal**: A guarded, idempotent, atomic migration brings an existing prior-build database in line with the new schema on open — dropping `comments`/`kudos` and rebuilding `activities` without the count columns — while preserving all other data and the raw archive.

**Independent Test**: Seed a DB with the OLD schema (comments/kudos rows + non-null count columns), open it via `connect()`, and verify the migration's postconditions (tables/columns gone, kept data + `raw_responses` intact, no visibility regression, `foreign_key_check` clean, structure == fresh DB), idempotency on re-open, and no-op on a fresh DB.

### Tests for User Story 3 (write to FAIL before implementation)

- [X] T018 [P] [US3] Create `tests/integration/test_migration_drop_comments_kudos.py`: seed an old-schema SQLite DB (embed the legacy DDL) with activities, comments, kudos rows, laps, `raw_responses` rows, and non-null `kudos_count`/`comment_count`; run `connect()`; assert postconditions 1–7 from `contracts/migration.md`; re-open to assert idempotency; assert a fresh-path DB is a no-op.
- [X] T027 [P] [US3] Add a resume-after-upgrade test (FR-012) to `tests/integration/test_migration_drop_comments_kudos.py`: seed a mid-backfill prior-build DB (populated `sync_state` frontier/phase + comments/kudos rows), open via `connect()`, and assert `sync_state` (frontier, phase, `backfill_complete`) is preserved and a subsequent backfill/poll step re-fetches no already-stored activity.

### Implementation for User Story 3

- [X] T019 [US3] Create `strava_mcp/db/migrations.py`: a guarded entry point (legacy detected via `sqlite_master`/`PRAGMA table_info(activities)`) that, when legacy is present, runs `PRAGMA foreign_keys=OFF`, a single transaction dropping `comments`/`kudos` then table-rebuilding `activities` without the count columns (`CREATE activities_new` → `INSERT…SELECT` kept cols → `DROP` → `RENAME` → recreate the 3 indexes), `COMMIT`, then `PRAGMA foreign_keys=ON` + `PRAGMA foreign_key_check`; idempotent no-op otherwise. Do not touch `raw_responses`/`detail_json`.
- [X] T020 [US3] Hook the migration into `strava_mcp/db/engine.py` `connect()` so it runs **before** `apply_schema()` on every open (depends on T019).

**Checkpoint**: Existing deployments upgrade cleanly with zero residual comments/kudos and no manual steps; all three stories green.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Bring the remaining human docs and fixtures in line, then validate end-to-end.

- [X] T021 [P] Update `README.md`: redefine the enrichment unit (remove "comments + kudos") and remove `get_comments(id)`/`get_kudos(id)` from the tool list.
- [X] T022 [P] Update `PRD.md`: remove comments/kudos from the enrichment description, the promoted-columns list (`kudos_count`/`comment_count`), the listed endpoints, the enrichment-order chain, and the tool list.
- [X] T023 [P] Update `PLAN.md`: rewrite the Slice 4 enrichment definition to `detail + laps + zones + streams` (no comments/kudos fetches or tools).
- [X] T024 [P] Add a superseded-by-003 note to `specs/001-strava-mcp-mirror/spec.md` and `specs/001-strava-mcp-mirror/data-model.md` indicating comments/kudos were removed in feature 003 (preserve historical scenarios; do not rewrite delivered history).
- [X] T025 [P] Update the fixture handler docstring in `tests/conftest.py` that references `/comments` and `/kudos` endpoints.
- [X] T026 Run `quickstart.md` validation: full `uv run pytest` green; the migration spot-check from quickstart §2; and the surface audit grep `grep -rin "kudos\|comment" strava_mcp/` returns no active references. Confirm SC-001 (4 requests/activity) and SC-004/SC-007.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (P1)**: no dependencies.
- **Foundational (P2)**: after Setup; blocks the rest (governance + vocabulary).
- **US1 (P3)**: after Foundational. MVP.
- **US2 (P4)**: after Foundational; shares `repositories/activities.py` with US1, so run after US1 to avoid same-file churn.
- **US3 (P5)**: after Foundational; logically pairs with US2's schema change (its migration targets the same end-state) — run after US2.
- **Polish (P6)**: after all desired stories.

### Within Each Story

- Tests written/updated to fail first, then implementation (regression-first, Principle II).
- US1: T007 ↔ T008 are a paired signature change (caller + repo) — keep adjacent, not parallel.
- US2: T013 before T014 (server registration depends on tool removal).
- US3: T019 before T020 (engine hook depends on the migration module).

### Parallel Opportunities

- Foundational: T003 ∥ T002 (different files).
- US1 tests: T004 ∥ T005 ∥ T006 ∥ T029.
- US2 tests: T009 ∥ T010 ∥ T011 ∥ T012 ∥ T028; impl T013 ∥ T017.
- US3 tests: T018 ∥ T027.
- Polish: T021 ∥ T022 ∥ T023 ∥ T024 ∥ T025.

---

## Parallel Example: User Story 1 tests

```bash
# Update all three US1 test files together (different files):
Task: "Update tests/integration/test_enrichment.py"
Task: "Update tests/integration/test_enrichment_streams_invariant.py"
Task: "Update tests/integration/test_dual_write.py"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & VALIDATE**: enrichment issues 4 requests/activity, activities still visible. This alone delivers the faster-sync goal.

### Incremental Delivery

- Setup + Foundational → governance ready.
- + US1 → faster sync (MVP, demoable rate-budget win).
- + US2 → complete surface/data removal (audit clean).
- + US3 → existing deployments upgrade safely.
- Polish → docs/fixtures aligned; full quickstart validation.

---

## Notes

- **Constitution gate (C1):** T002 (Principle III amendment, MAJOR bump) MUST land before — or in the same commit as — any removal code (US1+), so no intermediate commit violates the live constitution. It is first by design (Foundational Phase 2).
- [P] = different files, no incomplete-task dependency.
- `repositories/activities.py` is edited by both US1 (T008) and US2 (T015) in different regions — run the stories in order; do not parallelize across them.
- Preserve `raw_responses` and `detail_json` everywhere (clarification Option B) — only stop new writes; never scrub the archive.
- Commit after each task or logical group; each story checkpoint should leave its own tests green.
