# Feature Specification: Hide Empty (All-Zero) Stream Charts

**Feature Branch**: `004-hide-empty-stream-charts`

**Created**: 2026-06-09

**Status**: Draft

**Input**: User description: "When I open various activities on the dashboard, some stream graphs are empty — all zero because the metric doesn't apply to the activity (e.g. elevation in swimming). Detect when a stream has no usable data and show only the streams that are actually useful, without hardcoding what is shown per activity type."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Only meaningful stream charts are shown on an activity (Priority: P1)

A person viewing an activity detail page on the dashboard sees a chart for each
stream that carries real data, and does **not** see flat-line charts for streams
that contain no information for that activity. For example, an indoor weight-
training session or a pool swim shows heart rate (and, where present, speed,
cadence, temperature) but does **not** show an elevation chart pinned flat at
zero or a grade chart pinned flat at zero.

**Why this priority**: This is the entire feature. Phantom all-zero charts are
shown on roughly half of all activities today and actively mislead the viewer
into thinking a metric was recorded when it was not. Removing them is the core
user value and the MVP.

**Independent Test**: Open an indoor/no-GPS activity (e.g. a WeightTraining or
Swim session whose stored `altitude` and `grade_smooth` streams are entirely
zero) and confirm no elevation or grade chart appears, while heart rate and any
other genuinely-varying streams still render.

**Acceptance Scenarios**:

1. **Given** an activity whose `altitude` stream is present but every sample is
   zero, **When** the activity detail page is rendered, **Then** no elevation
   chart is shown.
2. **Given** an activity whose `grade_smooth` stream is present but every sample
   is zero, **When** the detail page is rendered, **Then** no grade chart is shown.
3. **Given** an activity whose `heartrate` stream contains varying non-zero
   values, **When** the detail page is rendered, **Then** the heart rate chart is
   shown unchanged.
4. **Given** an activity whose `cadence` stream mixes zeros and non-zero values
   (e.g. rowing with rest gaps), **When** the detail page is rendered, **Then**
   the cadence chart is still shown because it carries real data.

---

### User Story 2 - Activities with no usable streams degrade gracefully (Priority: P2)

When an activity has streams stored but every plottable stream turns out to be
all-zero (so every chart is suppressed), the page shows the existing "no stream
data" message rather than an empty Streams section or a broken layout.

**Why this priority**: An edge case that must not regress the page, but rarer
than US1 and handled by reusing existing fallback behavior.

**Independent Test**: Render an activity whose only plottable streams are
all-zero and confirm the Streams section shows the existing no-data message.

**Acceptance Scenarios**:

1. **Given** an activity where every plottable stream is all-zero, **When** the
   detail page is rendered, **Then** the Streams section shows the existing
   "no stream data for this activity" message and no charts.

---

### Edge Cases

- **All-zero vs. constant non-zero**: A stream that is constant at a non-zero
  value (e.g. a flat temperature reading) is **not** all-zero and MUST still be
  shown. Only the all-values-are-zero case is treated as "no data."
- **Partial zeros**: A stream containing at least one non-zero numeric sample is
  meaningful and MUST be shown, even if most samples are zero (e.g. cadence with
  rest periods, speed with stationary segments).
- **Negative values**: A stream containing negative values (e.g. grade) is
  meaningful — "all-zero" means literally every value equals zero, not "no value
  exceeds zero."
- **Non-numeric / missing samples**: Detection considers numeric samples; a
  stream with no numeric samples to plot is treated as having no usable data,
  consistent with today's behavior for absent or empty streams.
- **Absent streams**: Streams not stored for the activity continue to produce no
  chart, exactly as today (no change to this path).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The activity detail view MUST render a chart for a plottable stream
  only when that stream contains at least one non-zero numeric sample.
- **FR-002**: The system MUST suppress a plottable stream's chart when every
  numeric sample in that stream equals zero.
- **FR-003**: Stream suppression MUST be driven solely by the stored sample
  values, with no per-sport or per-stream-type hardcoded rules about which charts
  to show or hide.
- **FR-004**: A stream that is constant at a non-zero value MUST still be shown
  (it is not treated as empty).
- **FR-005**: A stream containing a mix of zero and non-zero numeric samples MUST
  still be shown.
- **FR-006**: When all plottable streams for an activity are suppressed, the
  Streams section MUST fall back to the existing "no stream data" message rather
  than render an empty section.
- **FR-007**: Behavior for streams that are absent or already empty MUST be
  unchanged by this feature.
- **FR-008**: The detection MUST not alter the stored stream data; it only affects
  what is displayed.

### Key Entities *(include if feature involves data)*

- **Stream**: A named time/position-indexed series for an activity (e.g. heart
  rate, power, speed, elevation, cadence, temperature, grade). Each has a list of
  per-sample values. The relevant new property is whether its numeric samples are
  *all zero* (no usable signal) versus carrying at least one non-zero value.
- **Activity detail view**: The rendered page that presents one chart per
  plottable stream that has usable data, plus a fallback message when none do.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For activities whose `altitude` and/or `grade_smooth` streams are
  entirely zero (roughly half of the existing library), the corresponding charts
  no longer appear on the detail page.
- **SC-002**: No activity gains or loses a chart for a stream that carries at
  least one non-zero sample — i.e. all genuinely-populated charts that render
  today continue to render.
- **SC-003**: Zero activities display a flat-at-zero chart after the change.
- **SC-004**: An activity whose every plottable stream is all-zero shows the
  no-stream-data fallback and renders without layout errors.

## Assumptions

- **All-zero is the chosen "no data" signal.** Per the analysis, hiding a chart
  when every numeric sample equals zero cleanly removes the phantom indoor
  elevation/grade charts and stationary-speed charts while preserving partial-data
  streams (rowing cadence, swim speed). A broader "zero-variance / constant" rule
  was considered and rejected because it would also hide a legitimately flat
  non-zero stream (e.g. a constant temperature reading observed in the data).
- **Scope is display-only.** This feature changes only which charts are shown on
  the activity detail page. It does not change sync, storage, the stored stream
  payloads, the raw store, or any MCP tool contract — consistent with the
  principle that stored data is never mutated and tools never fabricate or hide
  data at the storage layer.
- **The set of plottable stream types is unchanged.** The same stream types
  considered plottable today (heart rate, power, speed, elevation, cadence,
  temperature, grade) remain the candidates; only the per-activity show/hide
  decision changes.
- **The existing no-data fallback is reused.** The page already renders a
  "no stream data" message when there are no charts; this feature relies on that
  path when suppression empties the chart list.
- **This is a regression-class bug fix**, so a test reproducing the all-zero
  phantom chart (and one asserting partial-data streams survive) is expected
  before the fix lands, per project testing standards.
