# Phase 0 Research: Hide Empty (All-Zero) Stream Charts

All Technical Context items are known (no NEEDS CLARIFICATION). This file records
the design decisions and the empirical grounding behind them.

## Decision 1 — Suppression signal: "all numeric samples equal zero"

**Decision**: Suppress a plottable stream's chart when, after coercing its samples
to floats, every value equals `0`. Keep the chart if any sample is non-zero.

**Rationale**:
- It is the minimal, fully data-driven rule that matches the reported symptom
  ("graphs are empty, all zero"). An all-zero series carries no plottable signal
  regardless of sport, so hiding it is always safe.
- Empirically verified against the live mirror (628 activities with streams):

  | stream          | present | all-zero | const≠0 | has-null |
  |-----------------|--------:|---------:|--------:|---------:|
  | heartrate       |     627 |        0 |       0 |        0 |
  | watts           |      33 |        0 |       0 |        0 |
  | velocity_smooth |     356 |       30 |       0 |        0 |
  | altitude        |     628 |      314 |       0 |        0 |
  | cadence         |     226 |        0 |       0 |        0 |
  | temp            |     587 |        0 |       1 |        0 |
  | grade_smooth    |     628 |      315 |       0 |        0 |

  The rule hides exactly the 314 `altitude` + 315 `grade_smooth` + 30
  `velocity_smooth` phantom charts and nothing else. Partial-data streams (e.g.
  Rowing `cadence` min=0/max=33, Swim `velocity_smooth` min=0/max=1.94) have
  non-zero samples and are correctly kept.

**Alternatives considered**:
- **Zero-variance / constant (`min == max`)**: also hides flat *non-zero* lines.
  Rejected — it would hide the one observed constant-non-zero `temp` activity, and
  it would break the existing `test_charts_built_from_large_stream_stay_bounded`
  test (constant `heartrate = [130]*n`), which is legitimately meaningful data.
- **Per-sport hardcoded allow/deny lists** (e.g. "no elevation for Swim/Workout"):
  rejected by the spec — brittle, needs maintenance per new sport, and fails on
  outdoor activities recorded without a barometer. The value-based rule subsumes it.
- **Threshold / near-zero tolerance** (e.g. `abs(v) < epsilon`): rejected as
  unnecessary — the phantom data is exactly integer/float `0`, not noisy near-zero,
  so an exact `!= 0` test is sufficient and avoids hiding genuinely tiny real values.

## Decision 2 — Placement of the guard

**Decision**: Apply the check inside `build_activity_charts` immediately after the
existing `float()` coercion of the sample list (`charts.py` build loop), skipping
the series when `not any(ys)`. Do **not** modify `_data()`.

**Rationale**:
- `_data()` returns raw samples and is also used by `_x_axis()` to align the x
  basis (distance/time) by length. Filtering there risks length-mismatch surprises
  on the axis path. The build loop already produces the coerced `ys` used for
  plotting, so `not any(ys)` is the natural, localized place — it reuses work
  already done and touches only the y-series decision.
- `not any(ys)` is exactly "every element is zero/falsey" for a list of floats,
  and the preceding `try/except` already guarantees `ys` is all numeric.

**Alternatives considered**:
- Filtering in `_data()` — rejected (couples the axis-length logic to the
  suppression decision; see above).
- A separate `_is_all_zero()` helper — acceptable but unnecessary for a one-line
  predicate; a named helper can be introduced only if it improves readability of
  the test. Left to implementation discretion, no behavior change either way.

## Decision 3 — Empty-result handling

**Decision**: Rely on the existing fallback. `render.detail_page` already prints
"No stream data for this activity." when the `charts` list is empty
(`render.py:147`). When every plottable stream is all-zero and thus suppressed,
the list is empty and that branch fires — no new rendering code needed.

**Rationale**: Reuse over addition (YAGNI); the desired US2 behavior is already the
default for an empty chart list.

**Alternatives considered**: a distinct "all streams were empty" message —
rejected as scope creep; the generic no-data message is accurate and sufficient.
