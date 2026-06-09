# Contract: Activity Chart Builder

**Interface**: `strava_mcp.dashboard.charts.build_activity_charts(streams_payload) -> list[str]`

This is the internal UI contract consumed by `dashboard/handlers.py`. The feature
adds one clause (all-zero suppression); every other clause is the existing,
unchanged behavior and is restated here as a regression guard.

## Input

`streams_payload`: the `StreamsRepository.read` shape — `{"streams": {<type>:
{"data": [...]}, ...}}` — or `None`.

## Output

An ordered `list[str]` of inline-SVG chart fragments, one per **visible** plottable
stream, in the fixed order: heart rate, power, speed, elevation, cadence,
temperature, grade.

## Guarantees

1. **Null / empty input** → `[]`. `None` or `{"streams": {}}` yields no charts.
2. **Absent stream type** → no chart for that type (unchanged).
3. **Empty / non-numeric stream** → no chart (unchanged). A stream whose `data` is
   missing, empty, or has no values coercible to float produces no chart.
4. **NEW — All-zero stream** → no chart. A plottable stream whose every numeric
   sample equals `0` is suppressed (e.g. indoor `altitude`, indoor `grade_smooth`,
   stationary `velocity_smooth`).
5. **Mixed / non-zero stream** → chart shown. A stream with at least one non-zero
   numeric sample is plotted, even if other samples are zero (e.g. rowing
   `cadence` with rest gaps, swim `velocity_smooth`).
6. **Constant non-zero stream** → chart shown. A flat series at a non-zero value
   (e.g. constant `temp`, constant `heartrate`) is plotted (NOT treated as empty).
7. **Negative values count as data** → chart shown. "All-zero" means every value
   is literally `0`; a series containing negatives (e.g. `grade_smooth`) is visible.
8. **No mutation** → the function does not modify `streams_payload` or any stored
   data; it only decides what to return.
9. **Bounded output** → unchanged downsampling to `MAX_POINTS` still applies to any
   chart that is shown.

## Downstream behavior (unchanged, asserted by contract)

When `build_activity_charts` returns `[]` (including the new case where all
plottable streams were all-zero), `render.detail_page` renders the existing
"No stream data for this activity." message under the Streams heading. No new
rendering path is introduced.

## Acceptance mapping

| Spec requirement | Contract clause |
|------------------|-----------------|
| FR-001, FR-002   | 4, 5            |
| FR-003           | rule is value-based; no per-type/sport branch in clauses |
| FR-004           | 6               |
| FR-005           | 5               |
| FR-006           | Downstream behavior section |
| FR-007           | 2, 3            |
| FR-008           | 8               |
