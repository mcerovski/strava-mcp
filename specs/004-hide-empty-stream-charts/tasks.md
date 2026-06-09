---

description: "Task list for Hide Empty (All-Zero) Stream Charts"
---

# Tasks: Hide Empty (All-Zero) Stream Charts

**Input**: Design documents from `/specs/004-hide-empty-stream-charts/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/chart-builder.md, quickstart.md

**Tests**: INCLUDED. The constitution mandates regression-first testing (Principle II),
and the spec Assumptions require a failing test reproducing the all-zero phantom chart
before the fix. Test tasks are therefore written FIRST and must FAIL before implementation.

**Organization**: Tasks grouped by user story. This is a localized, display-only change —
one production guard in `strava_mcp/dashboard/charts.py` plus tests in
`tests/dashboard/test_charts.py` (and one render-fallback assertion).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 maps to user stories in spec.md
- All test tasks target the same file `tests/dashboard/test_charts.py`, so they are
  **sequential** (no `[P]` among themselves) to avoid edit conflicts.

## Path Conventions

Single project: source in `strava_mcp/`, tests in `tests/` at repo root (per plan.md).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish a green baseline before changing behavior.

- [X] T001 Run the existing chart suite as a baseline (`uv run pytest tests/dashboard/test_charts.py -q`) and confirm it passes on branch `004-hide-empty-stream-charts`, so any later failure is attributable to this change.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None required. This is a display-only change to an existing pure function;
there are no shared models, schema, migrations, or infrastructure to build. `render.py`
and `handlers.py` already provide the empty-chart-list fallback. Proceed directly to user stories.

**Checkpoint**: No foundational work — user stories can begin immediately after Setup.

---

## Phase 3: User Story 1 - Only meaningful stream charts are shown (Priority: P1) 🎯 MVP

**Goal**: Suppress the chart for any plottable stream whose every numeric sample is zero
(indoor `altitude`/`grade_smooth`, stationary `velocity_smooth`), while keeping streams
that carry any non-zero signal — with no per-sport hardcoding.

**Independent Test**: Build charts for an activity whose `altitude`/`grade_smooth` are all
zero and confirm those charts are absent; build charts for streams with mixed-zero,
constant-non-zero, and negative values and confirm they are present.

### Tests for User Story 1 (write first, must FAIL before T003) ⚠️

- [X] T002 [US1] Add failing unit tests in `tests/dashboard/test_charts.py` for value-based suppression: (a) an all-zero `altitude` stream yields no Elevation chart; (b) an all-zero `grade_smooth` stream yields no Grade chart; (c) a `cadence` stream mixing zeros and non-zero values yields a chart; (d) a constant non-zero stream (e.g. `temp = [26]*n`) yields a chart; (e) a `grade_smooth` stream containing negative values yields a chart. Map to contracts/chart-builder.md clauses 4–7.

### Implementation for User Story 1

- [X] T003 [US1] Implement the all-zero guard in `strava_mcp/dashboard/charts.py` `build_activity_charts`: after the existing `float()` coercion of the sample list (the `ys = [float(v) ...]` step), `continue` past the series when `not any(ys)`. Do not modify `_data()` or the `_x_axis` length logic. Make the T002 tests pass and keep `test_charts_built_from_large_stream_stay_bounded` (constant non-zero `heartrate`) green.

**Checkpoint**: All-zero charts are gone; partial/constant/negative streams still render. US1 is independently testable and demoable (MVP).

---

## Phase 4: User Story 2 - Activities with no usable streams degrade gracefully (Priority: P2)

**Goal**: When every plottable stream is all-zero (so all charts are suppressed), the page
shows the existing "No stream data for this activity." message and renders without errors.

**Independent Test**: Build charts for an activity whose only plottable streams are all-zero
and confirm `build_activity_charts` returns `[]`, and that the detail page renders the
no-data fallback for an empty chart list.

### Tests for User Story 2 (write first, must FAIL/PASS-by-fallback) ⚠️

- [X] T004 [US2] Add a unit test in `tests/dashboard/test_charts.py` asserting that when every plottable stream is all-zero (e.g. `altitude`, `grade_smooth`, `velocity_smooth` all zeros, plus only axis streams `time`/`distance`), `charts.build_activity_charts(payload)` returns `[]`. (Same file as T002 → run after T002.)
- [X] T005 [P] [US2] Add/confirm a test in `tests/dashboard/test_handlers.py` that `render.detail_page` shows "No stream data for this activity." when the `charts` list is empty (covers the suppression-empties-list path via the existing fallback). Different file from T004 → parallelizable once T003 lands.

### Implementation for User Story 2

- [X] T006 [US2] No production code change required — verify US2 is satisfied entirely by the T003 guard plus the existing `render.py:147` fallback; if T004/T005 reveal a gap, fix it in `strava_mcp/dashboard/render.py` (otherwise this task is a confirmation only).

**Checkpoint**: All-zero-only activities show the fallback message; US1 still works.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Validate the whole change against project quality gates.

- [X] T007 [P] Run full quality gates: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy strava_mcp` — all green, no new findings.
- [X] T008 Run the manual end-to-end checks in `specs/004-hide-empty-stream-charts/quickstart.md` §2 (indoor vs. outdoor activity) and confirm SC-001…SC-004.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Empty for this feature.
- **User Story 1 (Phase 3)**: Starts after Setup. T002 (tests) → T003 (guard).
- **User Story 2 (Phase 4)**: Depends on T003 (the guard). T004 after T002 (same file); T005 [P] after T003; T006 is verification.
- **Polish (Phase 5)**: After US1 and US2 complete.

### Within / across stories

- Tests written before implementation; T002 must fail before T003.
- T002 and T004 edit the same file (`tests/dashboard/test_charts.py`) → strictly sequential.
- T003 is the single shared production change; US2 reuses it (no second code change expected).

### Parallel Opportunities

- T005 ([P], `test_handlers.py`) can run alongside T004 once T003 has landed.
- T007 ([P]) gates can run together.
- Otherwise this feature is small and mostly sequential by design (shared files).

---

## Implementation Strategy

### MVP First (User Story 1)

1. T001 baseline green.
2. T002 add failing value-based suppression tests.
3. T003 add the `not any(ys)` guard → tests pass.
4. **STOP and VALIDATE**: US1 independently testable — phantom charts gone, real charts intact. Ship if ready.

### Incremental Delivery

1. Setup → US1 (MVP) → validate.
2. Add US2 (T004–T006) → confirm fallback for all-zero-only activities.
3. Polish (T007–T008) → full gates + manual quickstart.

---

## Notes

- [P] = different files, no dependencies.
- No schema, migration, or MCP tool contract change — rollback = revert the `charts.py` diff.
- Commit after T003 (MVP) and after T006; keep the regression test that reproduces the bug.
