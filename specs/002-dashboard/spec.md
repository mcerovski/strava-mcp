# Feature Specification: Local Data Dashboard

**Feature Branch**: `002-dashboard`

**Created**: 2026-06-05

**Status**: Draft

**Input**: User description: "I was thinking about extending this mcp server with database with data with new module that i can run separately from mcp (uv run strava-mcp dashboard). The new module would be UI dashboard displaying data from databse. Strava like dashboard with list of activities, timeline week, month, year. Also each activity could be opened and show data graphs for specific activity. Maybe if possible also show sync progress."

## Clarifications

### Session 2026-06-05

- Q: Should the per-activity detail view render the GPS route on a map? → A: No — defer maps to a later feature; v1 ships no map (preserves the loopback / no-external-network posture). `latlng` data may still feed non-map views.
- Q: Beyond summary + laps + stream graphs, what enrichment should the activity detail view show? → A: Also show segment efforts and HR/power zone distribution (the training-analysis data); omit social data (kudos/comments) for v1.
- Q: Should the dashboard cover only activities or also other mirrored resources? → A: Activities (list, detail, timeline) plus a small athlete identity/stats header; gear, starred segments, and routes are deferred.
- Q: How often should the sync-progress view auto-refresh? → A: No auto-refresh — the view shows the current persisted sync state on page load and updates only on a manual page reload.

## User Scenarios & Testing *(mandatory)*

The "user" here is the human owner of the mirrored Strava account — the person who set up the
server and authorized it against their own data. Unlike the MCP tool surface (whose user is an AI
agent), the dashboard is a visual, browser-based view a human opens to look at their own training
data after the **backfill** has populated the local mirror. The dashboard is a separate, read-only
module launched with `uv run strava-mcp dashboard`; it reads the same local database the sync worker
fills but never fetches from Strava and never writes to the mirror.

### User Story 1 - Browse all mirrored activities in a list (Priority: P1)

The owner launches the dashboard and immediately sees a scrollable, reverse-chronological list of
every fully-synced activity in the mirror — each row showing the essentials (date, sport type, name,
distance, moving time, elevation gain, average heart rate / power where present). They can filter the
list by sport type and by date range, and the list reflects exactly what is currently in the mirror.

**Why this priority**: The activity list is the foundational view — it is the entry point to every
other view and is independently useful on its own. With only this story shipped, the owner already has
a faster, friendlier way to see their mirrored data than querying the database by hand. It validates
the whole module: launching a separate process, reading the mirror safely while sync may be running,
and rendering activities in a browser.

**Independent Test**: With a populated mirror, run `uv run strava-mcp dashboard`, open the served page,
and confirm the list shows the same activities (and counts) present in the database, correctly ordered
newest-first, with sport-type and date-range filters narrowing the list as expected.

**Acceptance Scenarios**:

1. **Given** a mirror containing fully-synced activities, **When** the owner opens the dashboard,
   **Then** all fully-synced activities appear in a list ordered newest-first with their summary fields.
2. **Given** the list is displayed, **When** the owner filters by a sport type, **Then** only activities
   of that sport type remain visible and the result count updates.
3. **Given** the list is displayed, **When** the owner filters by a date range, **Then** only activities
   whose start date falls in that range remain visible.
4. **Given** an empty mirror (no activities yet synced), **When** the owner opens the dashboard,
   **Then** an explanatory empty state is shown rather than an error or a blank page.
5. **Given** an activity that has been listed but is not yet fully enriched, **When** the list renders,
   **Then** that activity is not shown (consistent with the "partial data is never exposed" rule).

---

### User Story 2 - Open one activity and view its data graphs (Priority: P2)

From the list, the owner clicks an activity and is taken to a detail view showing that activity's full
data: summary metrics, laps, **segment efforts**, HR/power zone distribution, and time-series graphs
derived from its **streams** (e.g. heart rate, power, speed/pace, elevation, cadence over time or
distance). This is the "deep dive" into a single workout. Social data (kudos and comments) is out of
scope for v1.

**Why this priority**: Viewing per-activity graphs is the primary reason a human opens a Strava-like
dashboard rather than reading a table. It depends on the list (P1) for navigation but delivers the
highest per-view value. It is independently testable once the list exists.

**Independent Test**: With at least one fully-synced activity that has streams, open its detail view and
confirm the graphs render from the stored stream data, the summary metrics match the activity record, and
laps are listed; for an activity whose streams are absent, confirm a graceful "no stream data" state.

**Acceptance Scenarios**:

1. **Given** an activity with stream data, **When** the owner opens its detail view, **Then** time-series
   graphs for the available stream types are rendered and labelled with units.
2. **Given** an activity detail view, **When** it loads, **Then** the activity's summary metrics, laps,
   segment efforts, and HR/power zone distribution match the values stored in the mirror.
3. **Given** an activity whose stream types are a subset (e.g. no power), **When** the detail view loads,
   **Then** only graphs for the present stream types are shown — absent types are omitted, not faked.
4. **Given** an activity id that does not exist in the mirror, **When** its detail view is requested,
   **Then** a not-found state is shown rather than an error page.

---

### User Story 3 - See training over week, month, and year timelines (Priority: P3)

The owner switches to a timeline view that groups activities into week, month, and year buckets and shows
aggregate totals per bucket (e.g. number of activities, total distance, total moving time, total elevation
gain), so they can see training volume and trends over time at a glance.

**Why this priority**: The timeline turns the raw list into insight (volume and consistency over time). It
is valuable but builds on the same data as the list and is not required for the dashboard to be useful, so
it ranks below the list and the per-activity deep dive.

**Independent Test**: With a multi-month mirror, open the timeline view, switch between week / month / year
groupings, and confirm each bucket's totals equal the sum of the matching activities in the mirror for that
period.

**Acceptance Scenarios**:

1. **Given** a populated mirror, **When** the owner selects the weekly grouping, **Then** activities are
   grouped into calendar weeks with per-week aggregate totals.
2. **Given** the timeline view, **When** the owner switches to monthly or yearly grouping, **Then** the
   buckets and totals recompute for that period without leaving the view.
3. **Given** a period with no activities, **When** the timeline renders, **Then** that period shows as an
   empty/zero bucket rather than being silently dropped (so gaps in training are visible).

---

### User Story 4 - Monitor sync progress (Priority: P4)

The owner opens (or glances at a panel on) the dashboard to see how far the **backfill** has progressed:
the current phase (backfilling vs. **fully synced** vs. polling), the **frontier** date reached, an estimate
of percent complete, total activities stored, the current rate-limit budget, and any active cooldown ETA.
The view shows the current persisted sync state when the page loads; the owner sees newer progress by
reloading the page (no automatic background refresh in v1).

**Why this priority**: The user themselves flagged this as optional ("maybe if possible"). It is genuinely
useful for a long-running backfill but is the least essential view and depends on no other story, so it is
ranked last and can ship independently.

**Independent Test**: With the sync worker running, open the sync-progress view and confirm it reports the
same phase, frontier date, counts, rate-limit budget, and cooldown ETA recorded in the mirror's sync state,
and that reloading the page after the worker has progressed shows the updated figures.

**Acceptance Scenarios**:

1. **Given** a backfill in progress, **When** the owner views sync progress, **Then** the current phase,
   frontier date, percent-complete estimate, and stored-activity count are shown.
2. **Given** the worker is in a rate-limit cooldown, **When** the owner views sync progress, **Then** the
   active cooldown and its expected end time are shown.
3. **Given** the mirror is fully synced, **When** the owner views sync progress, **Then** the view reports
   the fully-synced/polling state and the time of the last poll.
4. **Given** the dashboard is open while the worker advances, **When** the owner reloads the page, **Then**
   the progress figures reflect the latest persisted sync state.

---

### Edge Cases

- **No mirror / fresh database**: dashboard launched before any sync has run shows informative empty states
  for every view, never a crash or stack trace.
- **Sync running concurrently**: the dashboard reads while the worker writes; it must never block the worker
  or take a write lock, and figures may legitimately change between views.
- **Worker not running**: the dashboard still opens and shows the last-known data and sync state from the
  mirror; the sync-progress view simply stops advancing.
- **Database missing or unreadable**: launching the dashboard surfaces an actionable message (how to point at
  or create the mirror) rather than an opaque error.
- **Activities without streams** (e.g. manually-entered workouts): detail view degrades gracefully to summary
  + laps with a clear "no stream data" note.
- **Very large mirror** (thousands of activities): the list and timeline remain responsive (pagination or
  virtualized scrolling rather than rendering everything at once).
- **Port already in use**: if the dashboard's local port is taken, the owner is told how to choose another.
- **Owner opens an activity id that is in the raw store but not the normalized/enriched tables**: treated as
  not-yet-visible (not-found), consistent with the partial-data rule.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a `dashboard` subcommand runnable as `uv run strava-mcp dashboard`
  that starts a local, browser-accessible UI as a process separate from the `serve` (MCP + worker) process.
- **FR-002**: The dashboard MUST be strictly read-only with respect to the mirror — it MUST NOT write to the
  database and MUST NOT call the Strava API. All displayed data comes from the existing local mirror.
- **FR-003**: The dashboard MUST read the same local database that `serve` populates, using a concurrent-reader
  access pattern that never blocks or locks out the single writer (the sync worker).
- **FR-004**: The dashboard MUST display a list of activities ordered newest-first, showing each activity's
  key summary fields (at minimum: start date, sport type, name, distance, moving time, elevation gain, and
  average heart rate / power when present).
- **FR-005**: The activity list MUST be filterable by sport type and by date range, and MUST show a result
  count reflecting the active filters.
- **FR-006**: The dashboard MUST show only fully-enriched activities; activities that are listed-but-not-yet-
  enriched MUST NOT appear in any view.
- **FR-007**: The dashboard MUST provide a per-activity detail view reachable from the list, showing the
  activity's summary metrics, laps, segment efforts, and HR/power zone distribution. Social data (kudos and
  comments) is out of scope for v1.
- **FR-008**: The activity detail view MUST render time-series graphs from the activity's stored streams for
  whichever stream types are present (e.g. heart rate, power, speed/pace, elevation, cadence), omitting graphs
  for absent stream types.
- **FR-008a**: The activity detail view MUST omit segment efforts and the zone distribution gracefully (rather
  than erroring) for activities that recorded none, consistent with the "partial data is never faked" rule.
- **FR-009**: The dashboard MUST provide a timeline view that groups activities by calendar week, month, and
  year, with per-bucket aggregate totals (count, total distance, total moving time, total elevation gain).
- **FR-010**: The timeline view MUST let the owner switch between week, month, and year groupings without
  leaving the view, recomputing buckets and totals for the selected grouping.
- **FR-011**: The dashboard MUST provide a sync-progress view reporting the current sync phase, frontier date,
  a percent-complete estimate, stored-activity count, current rate-limit budget, and active cooldown ETA when
  one applies, sourced from the mirror's sync state.
- **FR-012**: The sync-progress view MUST display the current persisted sync state at page-load time and
  reflect the latest persisted state on each manual page reload. Automatic background refresh is out of scope
  for v1.
- **FR-013**: Every view MUST present an informative empty/degraded state (rather than an error) when the
  underlying data is absent — empty mirror, activity without streams, or worker not running.
- **FR-014**: When the database cannot be located or opened, the dashboard MUST fail with an actionable
  operator-facing message (consistent with the project's actionable-failure-mode rule) rather than a stack
  trace.
- **FR-015**: The dashboard MUST remain responsive for large mirrors (thousands of activities), avoiding
  rendering the entire dataset at once for the list and timeline views.
- **FR-016**: The dashboard's network surface MUST be bound to the local loopback interface only, consistent
  with the project's single-user, loopback-only posture (no external network exposure, no added auth layer).
- **FR-017**: All figures, labels, and status text in the dashboard MUST use the project's fixed vocabulary
  (backfill, frontier, poll, fully synced, enrichment, activity, stream, segment effort, athlete) and avoid
  the proscribed synonyms.
- **FR-018**: The dashboard MUST display a small athlete identity/stats header (e.g. name and high-level
  totals from the stored athlete record) for context.
- **FR-019**: The dashboard's scope for v1 is activities (list, detail, timeline), the sync-progress view, and
  the athlete header. Dedicated views for gear, starred segments, and routes are out of scope for v1.
- **FR-020**: The activity detail view MUST NOT render a GPS route map in v1 (maps are deferred to a later
  feature to preserve the no-external-network posture); stored `latlng` data may still feed non-map views.

### Key Entities *(include if feature involves data)*

- **Activity**: A single recorded workout shown as a list row and as a detail page; carries summary metrics
  (date, sport type, distance, times, elevation, heart rate, power) always, and full enrichment (laps, streams)
  when the backfill has reached it. Source of the list, detail, and timeline views.
- **Stream**: The per-sample time series for one activity (heart rate, power, speed, altitude, cadence, etc.);
  the data behind the per-activity graphs. Present only for enriched activities that recorded that signal.
- **Lap**: A segment of one activity with its own metrics; listed within the activity detail view.
- **Segment effort**: One attempt by the athlete at a Strava segment during an activity; listed within the
  activity detail view (distinct from the segment itself).
- **Zone distribution**: The HR/power time-in-zone breakdown stored for an activity; shown in the detail view.
- **Athlete**: The single account the mirror belongs to; provides identity and high-level stats for the
  dashboard header.
- **Sync state**: The mirror's record of backfill phase, frontier date, newest-synced cursor, fully-synced
  flag, last poll time, rate-limit budget, and cooldown — the source for the sync-progress view.
- **Timeline bucket**: A derived (not stored) grouping of activities by calendar week / month / year with
  aggregate totals, computed on read for the timeline view.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a populated mirror, the owner can launch the dashboard and see their activity list in under
  10 seconds from running the command, with no manual configuration beyond what `serve` already requires.
- **SC-002**: The activity list and every timeline bucket show totals that exactly match the activities present
  in the mirror for the same filters/period (100% agreement, no missing or double-counted activities).
- **SC-003**: Opening any fully-synced activity that recorded streams renders its graphs in under 2 seconds on
  a typical multi-year mirror.
- **SC-004**: After the worker advances (stored-activity count or frontier changes), reloading the
  sync-progress page reflects the new persisted figures.
- **SC-005**: Running the dashboard while a backfill is in progress causes no measurable slowdown or lock
  contention for the sync worker (the worker's write throughput is unaffected).
- **SC-006**: No view ever displays a partially-enriched activity, and no view ever issues a Strava API call
  (verifiable: zero outbound Strava requests originate from the dashboard process).
- **SC-007**: Every documented edge case (empty mirror, missing database, activity without streams, worker not
  running, port in use) results in an informative message, not a crash or stack trace.

## Assumptions

- The dashboard is for the single human owner of the mirrored account, viewed locally in their own browser;
  it reuses the project's single-user, loopback-only posture and adds no authentication layer (FR-016).
- The dashboard reads the existing local SQLite mirror at the project's configured database path; it requires
  no new credentials or OAuth scope and never contacts Strava.
- "Run separately from mcp" means a distinct process/command (`dashboard`) that can run while `serve` runs;
  the dashboard does not start or manage the sync worker, and the worker does not depend on the dashboard.
- The sync-progress view reflects whatever the worker has committed to the mirror's sync state as of page
  load; there is no automatic background refresh in v1 (clarified 2026-06-05), so the owner reloads to see
  newer figures, and if the worker is not running the view simply shows the last persisted state.
- The browser is assumed to be modern and run on the same machine as the dashboard process.
- Route maps (rendering an activity's GPS track on a map) are out of scope for v1 (clarified 2026-06-05),
  deferred to a later feature because map tiles would introduce an external dependency that conflicts with
  the project's no-external-network posture; GPS/`latlng` data may still drive non-map views.
- Choice of UI rendering approach (server-rendered pages, a single-page app, charting library, default port)
  is an implementation decision for the planning phase and is intentionally left out of this specification.
- The timeline uses the athlete's local activity start dates for bucketing into calendar weeks/months/years.
