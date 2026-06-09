# Phase 1 Data Model: Hide Empty (All-Zero) Stream Charts

This feature introduces **no new persisted entities and no schema change**. It adds
one derived, in-memory property used at render time. Documented here for clarity.

## Entities

### Stream (existing, in-memory render view)

The per-type series read from `activity_streams.streams_json` and passed to the
chart builder as `{"streams": {<type>: {"data": [...]}, ...}}`.

| Field            | Type            | Notes                                                        |
|------------------|-----------------|--------------------------------------------------------------|
| type             | string          | e.g. `heartrate`, `altitude`, `grade_smooth` (existing key)  |
| data             | list of numbers | per-sample values (existing)                                 |

**Derived property (new, computed at render — not stored):**

- `is_all_zero`: `true` when the stream has at least one numeric sample **and**
  every numeric sample equals `0`. Used only to decide chart visibility.

**Visibility rule (the feature):**

A plottable stream produces a chart **iff** it has at least one numeric sample that
is non-zero — i.e. it is present, non-empty, coercible to numbers, and
`is_all_zero == false`.

| Stream condition                          | Chart shown? | Change from today |
|-------------------------------------------|:------------:|-------------------|
| Absent (key not in streams)               |      No       | unchanged          |
| Present, empty list / no numeric samples  |      No       | unchanged          |
| Present, **all numeric samples = 0**      |   **No**      | **NEW — was Yes**  |
| Present, mix of zero and non-zero         |      Yes       | unchanged          |
| Present, constant non-zero                |      Yes       | unchanged          |
| Present, varying values                   |      Yes       | unchanged          |

### Plottable stream types (existing, unchanged)

The candidate set is unchanged: `heartrate`, `watts`, `velocity_smooth`,
`altitude`, `cadence`, `temp`, `grade_smooth` (order defines chart order). Axis /
positional streams (`time`, `distance`, `latlng`, `moving`) are never plotted.

### Activity detail view (existing, unchanged structure)

Renders one chart per *visible* plottable stream; when the visible set is empty,
renders the existing "No stream data for this activity." message. No structural
change — only the membership of the visible set changes.

## State / transitions

None. The visibility decision is a pure function of stored sample values at render
time; there is no persisted state and no mutation of `streams_json` or the raw store.
