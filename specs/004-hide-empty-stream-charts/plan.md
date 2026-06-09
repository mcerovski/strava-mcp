# Implementation Plan: Hide Empty (All-Zero) Stream Charts

**Branch**: `004-hide-empty-stream-charts` | **Date**: 2026-06-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-hide-empty-stream-charts/spec.md`

## Summary

Roughly half of all activities render phantom flat-at-zero charts (indoor
`altitude`/`grade_smooth`, stationary `velocity_smooth`) because the chart
builder only checks whether a stream's sample list is *non-empty*, never whether
the samples carry any signal. The fix is a single value-aware guard in the chart
builder: after a stream's samples are coerced to numbers, suppress the chart when
every numeric sample equals zero. No per-sport rules, no storage changes, no tool
contract changes — display-only. The existing "no stream data" fallback already
covers the case where suppression empties the chart list.

## Technical Context

**Language/Version**: Python 3.11 (`requires-python >=3.11`)

**Primary Dependencies**: None new. The chart builder (`strava_mcp/dashboard/charts.py`)
is pure stdlib (`html`, inline-SVG strings — no JS/CDN). Dashboard served via the
existing in-repo HTTP handler stack.

**Storage**: SQLite mirror (read-only on this path). **No schema or data change** —
stored `activity_streams.streams_json` is untouched; the change is purely in how
stored streams are rendered.

**Testing**: pytest (`tests/dashboard/test_charts.py` is the unit home for the
chart builder).

**Target Platform**: Local loopback dashboard (Linux), single user.

**Project Type**: Single project — library + CLI + local HTTP dashboard.

**Performance Goals**: Unchanged. The new guard is an O(n) scan over the
already-in-memory sample list per plottable stream, before the existing
downsample/render. Negligible against the current per-chart work and bounded by
stream length.

**Constraints**: No new dependencies; display-only; stored data never mutated;
reuse the existing no-data fallback; honor CONTEXT.md vocabulary.

**Scale/Scope**: One source file (`charts.py`) and one test file
(`tests/dashboard/test_charts.py`). ~5–10 lines of production change.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Code Quality & Architectural Integrity** — PASS. Change is confined to the
  `dashboard` rendering module; no module boundary is crossed, no SQL added, no
  network call. The chart builder stays a pure function of stored streams. No
  promoted columns or new abstractions. Vocabulary (CONTEXT.md) respected.
- **II. Testing Standards (NON-NEGOTIABLE)** — PASS by plan. This is a
  regression-class bug fix, so a failing test that reproduces the all-zero phantom
  chart is added before the fix, plus tests asserting partial-data and
  constant-non-zero streams survive. No live Strava calls (pure unit test over an
  in-memory payload). The existing `test_charts_built_from_large_stream_stay_bounded`
  (constant non-zero `heartrate`) must keep passing — confirming the all-zero rule
  does not regress constant-non-zero streams.
- **III. User Experience Consistency** — PASS / reinforced. "Partial data is never
  exposed" and "never fabricated" — an all-zero flat line is a fabricated-looking
  signal; suppressing it makes the surface more honest. The activity is still fully
  enriched; this is display filtering, not exposure of half-enriched data, and no
  MCP tool return shape changes (stable schemas preserved).
- **IV. Performance & Rate-Limit Discipline** — PASS. No new queries; streams stay
  stored as JSON; the added work is an O(n) in-memory check on data already loaded
  for rendering, well within the existing bounded-render budget.

**Result**: No violations. Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/004-hide-empty-stream-charts/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── chart-builder.md # Phase 1 output — behavioral contract for build_activity_charts
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
strava_mcp/dashboard/
├── charts.py            # CHANGE: add all-zero suppression in the build loop
├── render.py            # UNCHANGED — existing "No stream data" fallback already covers empty list
└── handlers.py          # UNCHANGED — already calls build_activity_charts then render.detail_page

tests/dashboard/
└── test_charts.py       # CHANGE: add regression + partial-data + constant-non-zero coverage
```

**Structure Decision**: Single-project layout, already established. The feature is
a localized, display-only change to the existing `dashboard/charts.py` chart
builder and its unit test. No new modules, files, or directories in the source
tree; `render.py` and `handlers.py` are deliberately untouched because the empty
chart-list path is already handled.

## Complexity Tracking

> No Constitution Check violations — section intentionally empty.
