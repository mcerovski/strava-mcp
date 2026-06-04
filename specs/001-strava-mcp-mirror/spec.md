# Feature Specification: Strava MCP Local Mirror

**Feature Branch**: `001-strava-mcp-mirror`

**Created**: 2026-06-04

**Status**: Draft

**Input**: User description: "A locally-run MCP server that authenticates to Strava once, mirrors the athlete's full Strava history into a local database, and serves that data to AI agents as pure database reads (PRD.md, CONTEXT.md, PLAN.md)."

## User Scenarios & Testing *(mandatory)*

The system has two distinct users: the **operator** (the person who owns the Strava
account and runs the server locally) and the **agent** (an AI client that queries the
served data). Operator journeys are about getting data flowing; agent journeys are about
reading it. Vocabulary follows CONTEXT.md (backfill, frontier, poll, enrichment, fully
synced, raw store).

### User Story 1 - Authorize the mirror once (Priority: P1)

The operator grants the mirror read access to their full Strava account in a single,
deliberate step. They run the authorization command, approve the requested read scopes in
their browser, and the credentials are captured and stored locally so that future runs
never need re-authorization (the credentials refresh themselves).

**Why this priority**: Nothing else can happen without authorized, full-read credentials.
This is the one human-in-the-loop step and the prerequisite for every other story.

**Independent Test**: Run the authorization command; confirm the browser opens to the
consent screen for the full read scopes, approval is captured automatically (no manual
copy-paste), credentials are persisted locally, and a probe read of the athlete's activity
list succeeds — proving the granted access actually works.

**Acceptance Scenarios**:

1. **Given** no stored credentials, **When** the operator runs authorization and approves
   the full read scopes, **Then** access credentials, refresh credentials, expiry, and
   granted scope are persisted locally and a verification read returns success.
2. **Given** the consent screen cannot open a browser (headless), **When** authorization
   runs, **Then** the authorization URL is printed for the operator to open manually and
   approval is still captured automatically by the local callback.
3. **Given** previously stored credentials exist, **When** any later run needs access,
   **Then** the stored credentials take precedence over the initial seed and are refreshed
   automatically before they expire — with no operator action.

---

### User Story 2 - Serve the athlete profile to an agent (Priority: P1)

With valid credentials, the operator starts the server. It refuses to start (with concrete
instructions) if the stored credentials lack the required read scopes. Once running, an
agent connects and asks for the athlete's profile, zones, and rolled-up stats, and receives
them as a read from the local mirror — the agent never touches Strava directly.

**Why this priority**: This proves the full path end-to-end (authorize → fetch → store →
serve) on one resource. It is the smallest slice that delivers agent-visible value and
de-risks every later resource.

**Independent Test**: Start the server with a valid full-scope credential; have an agent
request the athlete profile and confirm it returns the stored profile, zones, and stats.
Separately, start with an insufficient-scope credential and confirm the server exits with
an actionable instruction to re-authorize.

**Acceptance Scenarios**:

1. **Given** stored credentials missing a required read scope, **When** the operator starts
   the server, **Then** it exits printing the exact command to run to re-authorize, rather
   than failing silently or with a stack trace.
2. **Given** valid full-scope credentials, **When** the server starts, **Then** it serves
   on the local loopback interface and begins mirroring the athlete profile, zones, and
   stats in the background.
3. **Given** the profile has been mirrored, **When** an agent requests the athlete profile,
   **Then** it receives profile, zones, and stats served entirely from the local mirror.

---

### User Story 3 - Browse and query the activity history (Priority: P1)

The mirror sweeps the athlete's entire activity history newest-first (the **backfill**),
storing each activity's summary as the **frontier** moves back through time. An agent can
list activities filtered by date range and sport type, fetch a single activity, and check
**sync status** to understand how much history is present and what the mirror is doing right
now (frontier date, percent complete, whether it is rate-limited and for how long).

**Why this priority**: Activities are the central entity and the primary reason the mirror
exists. Newest-first backfill means useful recent data is queryable almost immediately,
while older history continues to stream in. Sync status makes the in-progress state honest
and reasoned-about.

**Independent Test**: Start a fresh mirror; confirm activities appear newest-first and that
listing by date range and sport type returns the right subset; restart mid-backfill and
confirm it resumes from the frontier without re-fetching; confirm sync status reports a
plausible frontier date, percent complete, counts, and rate-limit budget.

**Acceptance Scenarios**:

1. **Given** a backfill in progress, **When** an agent lists activities filtered by date
   range and/or sport type, **Then** only matching activities already mirrored are returned.
2. **Given** the mirror is interrupted and restarted mid-backfill, **When** it resumes,
   **Then** it continues from the frontier with no re-fetching of already-stored activities.
3. **Given** the read budget for the current window is exhausted, **When** the mirror hits
   the limit, **Then** it pauses until the known next reset and resumes automatically, and
   sync status reflects the pause and its expected end time.
4. **Given** any point during or after backfill, **When** an agent requests sync status,
   **Then** it receives frontier date, percent complete, a fully-synced flag, counts,
   current rate-limit budget, and cooldown end time.

---

### User Story 4 - Read full per-activity detail (Priority: P2)

As the frontier reaches each activity, the mirror enriches it as one complete unit — full
detail plus laps, comments, kudos, and zones — and the athlete's segment efforts for that
activity are captured from the activity itself. An agent can then read the full detail and
each of those facets. An activity becomes visible to the agent only once it is fully
enriched; partially-enriched activities are never exposed.

**Why this priority**: Summaries answer "what did I do"; enrichment answers "how did it go"
(laps, social, effort distribution). It is the first deep layer of value and a prerequisite
for streams and segment-effort queries.

**Independent Test**: Let the backfill enrich an activity; confirm an agent can read its
full detail, laps, comments, kudos, and zones, and that its segment efforts are present —
all without any live Strava call by the read tools.

**Acceptance Scenarios**:

1. **Given** the frontier has reached an activity, **When** enrichment runs, **Then** the
   activity's detail, laps, comments, kudos, zones, and segment efforts are all stored as a
   single unit before the activity is marked visible.
2. **Given** an activity that is only partway through enrichment, **When** an agent queries
   it, **Then** it is not returned as available (no partial activity is ever exposed).
3. **Given** a fully enriched activity, **When** an agent requests detail, laps, comments,
   kudos, or zones, **Then** each is served from the local mirror.

---

### User Story 5 - Access activity streams (Priority: P2)

Enrichment also fetches each activity's streams (the per-sample time series such as
heartrate, power, location, altitude, cadence, speed). An agent can request the stored
streams for an activity, optionally narrowing to specific stream types; if the frontier has
not yet reached that activity, the agent receives a clear "not yet synced" signal instead of
an error or a fabricated result.

**Why this priority**: Streams are the bulk of the data by volume and unlock fine-grained
analysis, but they depend on enrichment existing first. They also complete the definition of
"fully synced."

**Independent Test**: For an enriched activity, request its streams and confirm the
requested types come back with their metadata; for an activity the frontier has not reached,
confirm the "not yet synced" signal is returned.

**Acceptance Scenarios**:

1. **Given** an enriched activity, **When** an agent requests its streams (optionally by
   type), **Then** the requested stream types are returned with their metadata.
2. **Given** an activity the frontier has not yet reached, **When** an agent requests its
   streams, **Then** a clear "not yet synced" signal is returned.
3. **Given** every mirrored activity now carries its streams and the frontier has reached
   the first-ever activity, **When** sync status is checked, **Then** the fully-synced flag
   reads true.

---

### User Story 6 - Read gear, routes, and starred segments (Priority: P2)

The mirror also captures the athlete's gear, routes (as metadata plus map outline, not
file exports), and starred segments (in full). An agent can list and read each of these,
and can read the athlete's efforts against any segment. Segments merely encountered during
activities are kept as the summary embedded in those activities — they are not expanded
into full segment records.

**Why this priority**: These round out the athlete's world (equipment, planned routes,
favorite segments) but are reference data secondary to the activity history itself.

**Independent Test**: Confirm an agent can list and read gear, routes, and starred segments,
that a starred segment returns full detail while an encountered one returns only its
embedded summary, and that efforts for a given segment are listable.

**Acceptance Scenarios**:

1. **Given** the athlete references gear on their profile, **When** an agent lists or reads
   gear, **Then** every referenced piece of gear is available.
2. **Given** the athlete has routes, **When** an agent lists or reads a route, **Then** it
   receives route metadata and map outline (no downloadable file export).
3. **Given** a starred segment and a merely-encountered segment, **When** an agent reads
   each, **Then** the starred one returns full detail and the encountered one returns its
   embedded summary, with no extra per-segment fetch performed.
4. **Given** stored segment efforts, **When** an agent lists efforts for a segment,
   **Then** the athlete's attempts at that segment are returned.

---

### User Story 7 - Stay current with new activities (Priority: P3)

Once the mirror is fully synced, it shifts to steady-state **polling**: on a regular cadence
it checks for new activities using a look-back window, dedupes by activity id, and enriches
and inserts only activities it has not seen — catching back-dated uploads without ever
mutating existing records. The operator (or agent) can also nudge a poll to run immediately.

**Why this priority**: Keeps the mirror useful over time, but only matters after the
historical backfill is complete, so it follows the backfill-centric stories.

**Independent Test**: With a fully-synced mirror, trigger a poll and confirm a newly added
activity (including one back-dated within the look-back window) is enriched and inserted,
while existing activities are untouched.

**Acceptance Scenarios**:

1. **Given** a fully-synced mirror, **When** the poll cadence elapses, **Then** the mirror
   lists recent activities with a look-back window and enriches/inserts only ids not already
   stored.
2. **Given** a back-dated upload whose start falls within the look-back window, **When** the
   next poll runs, **Then** it is detected and added.
3. **Given** activities edited or deleted on Strava, **When** the poll runs, **Then**
   existing local records are not mutated or removed (insert-only).
4. **Given** an agent or operator wants fresh data now, **When** an immediate poll is
   requested, **Then** the poll runs at once and reports its outcome.

---

### User Story 8 - Summarize training at a glance (Priority: P3)

An agent can request a roll-up of the athlete's training over a period (for example weekly
or monthly), optionally for a single sport — counts, total distance, time, and elevation —
computed cheaply from the mirror so the agent can answer trend questions without pulling
every activity.

**Why this priority**: A convenience layer over data already present; valuable for trend
answers but not required for the mirror to function.

**Independent Test**: With activities mirrored, request a training summary for a period and
optional sport and confirm the roll-ups match the underlying activities.

**Acceptance Scenarios**:

1. **Given** mirrored activities, **When** an agent requests a training summary for a
   period, **Then** it receives correct counts, distance, time, and elevation per period.
2. **Given** a sport filter, **When** the summary is requested, **Then** only that sport's
   activities are included.

---

### Edge Cases

- **Insufficient scope at serve time**: the initial seed credential may carry only a
  minimal scope; the server must refuse to start and tell the operator to re-authorize for
  the full read scopes.
- **Rate-limit exhaustion mid-page**: the mirror must pause to the known next window reset
  (not a blind retry) and resume from the last checkpoint, with status reflecting the wait.
- **Server restart mid-backfill**: resumption must not re-fetch already-stored activities.
- **Activity requested before the frontier reaches it**: reads return a clear "not yet
  synced" signal, never a partial or fabricated result.
- **Back-dated upload outside the look-back window**: an upload back-dated further than the
  look-back window is not guaranteed to be caught by polling (documented limitation).
- **Edits/deletes on Strava after mirroring**: not reflected locally (insert-only).
- **Empty account / first-ever activity**: backfill must terminate correctly when it reaches
  the athlete's first-ever activity (or when there are none).
- **Concurrent agent reads during backfill**: many agents may read while the mirror writes;
  reads must not block on or be blocked by the writer.

## Requirements *(mandatory)*

### Functional Requirements

**Authorization & credentials**
- **FR-001**: The system MUST let the operator authorize the mirror in a single deliberate
  step that requests full read access to the athlete's Strava account (including private
  data) and requests no write access.
- **FR-002**: Authorization MUST capture the approval automatically via a local callback
  (no manual copy-paste) and MUST fall back to printing the authorization URL when no
  browser can be opened.
- **FR-003**: The system MUST persist the granted credentials (access, refresh, expiry,
  scope) locally and MUST refresh access automatically before expiry without operator
  action.
- **FR-004**: Stored credentials MUST take precedence over the initial seed once present.
- **FR-005**: Authorization MUST verify success by performing a probe read that requires the
  granted scope and reporting the scopes actually granted.

**Serving & access control**
- **FR-006**: The server MUST refuse to start when stored credentials lack a required read
  scope, exiting with the concrete command to re-authorize.
- **FR-007**: The server MUST serve only on the local loopback interface (single-user,
  local-only) and MUST survive across multiple agent sessions and concurrent clients.
- **FR-008**: Every agent-facing read MUST be served from the local mirror; no agent-facing
  read may contact Strava directly.

**Mirroring (backfill)**
- **FR-009**: The system MUST mirror the athlete's complete activity history in a
  newest-to-oldest **backfill** sweep, advancing a **frontier** and checkpointing
  frequently enough that an interrupted run resumes without re-fetching stored activities.
- **FR-010**: As the frontier reaches each activity, the system MUST **enrich** it as one
  complete unit (detail, laps, comments, kudos, zones, and streams) and MUST capture the
  athlete's segment efforts for that activity from the activity itself.
- **FR-011**: An activity MUST become agent-visible only after it is fully enriched; the
  system MUST NOT expose partially-enriched activities.
- **FR-012**: The system MUST mirror the athlete profile, zones, and rolled-up stats, the
  athlete's gear, routes (metadata and map outline only — no file export), and starred
  segments (in full detail).
- **FR-013**: Segments merely encountered during activities MUST be retained as their
  embedded summary and MUST NOT trigger an additional per-segment fetch.
- **FR-014**: The system MUST preserve every fetched resource verbatim in an append-only
  raw store in addition to its queryable form, so the queryable form is rebuildable.

**Rate-limit discipline**
- **FR-015**: The system MUST track the remaining read budget from each response and, on
  exhaustion or an explicit limit signal, MUST pause until the known next window reset
  rather than retrying blindly, then resume from the last checkpoint.

**Steady-state poll**
- **FR-016**: After the mirror is fully synced, the system MUST **poll** for new activities
  on a regular cadence, using a look-back window and deduping by activity id so that
  back-dated uploads within the window are caught.
- **FR-017**: Polling MUST insert only previously-unseen activities and MUST NOT mutate or
  delete existing records (edits and deletes on Strava are not reflected).
- **FR-018**: The system MUST let an agent or operator trigger an immediate poll on demand
  and report its outcome.

**Agent read surface**
- **FR-019**: The system MUST expose reads for: athlete profile/zones/stats; activity lists
  filtered by date range and sport type; a single activity's full detail; an activity's
  laps, comments, kudos, zones, and streams; gear (list and single); routes (list and
  single); starred segments (list and single) and a segment's efforts.
- **FR-020**: When an agent requests data for an activity the frontier has not yet reached,
  the system MUST return a clear "not yet synced" signal rather than an error or fabricated
  result.
- **FR-021**: The system MUST expose **sync status** reporting frontier date, percent
  complete, a fully-synced flag, resource counts, current rate-limit budget, and cooldown
  end time.
- **FR-022**: The system MUST expose a training summary roll-up over a period (e.g. weekly,
  monthly) with an optional sport filter, returning counts, distance, time, and elevation.

**Observability & safety**
- **FR-023**: The system MUST log progress (current activity, frontier date, rate-limit
  budget, cooldown end time) to both the terminal and a local log file, and MUST NOT write
  credentials or secrets to logs or to any location outside the local data directory.

### Key Entities *(include if feature involves data)*

- **Athlete**: the single Strava account the mirror represents; profile, zones, and
  rolled-up stats. One athlete per mirror — no multi-athlete concept.
- **Activity**: a single recorded workout (run, ride, swim…); the central entity. Carries
  summary fields always and full enrichment once the frontier reaches it.
- **Enrichment facets** (each tied to an activity): **laps**, **comments**, **kudos**,
  **zones** (effort distribution), and **streams** (per-sample time series — the bulk of
  stored data).
- **Segment effort**: one attempt by the athlete at a segment during an activity; distinct
  from the segment itself.
- **Segment**: a stretch of road/trail; **starred** segments are stored in full detail,
  **encountered** segments only as the summary embedded in activities.
- **Gear**: bikes and shoes referenced by the athlete.
- **Route**: a planned route stored as metadata and map outline only.
- **Raw store**: append-only verbatim copy of every fetched response, kept as a durable
  backup independent of the queryable form.
- **Sync state**: the mirror's own bookkeeping — frontier, newest-synced cursor, run
  history, and rate-limit snapshots — backing sync status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator completes first-time authorization in a single sitting (one
  consent approval, no manual code copying) and reaches a running, serving mirror.
- **SC-002**: Once the athlete profile is mirrored, an agent retrieves it in under 2 seconds
  (a local DB read), and the agent makes no Strava call.
- **SC-003**: Recent activities are queryable from the mirror shortly after backfill begins
  (newest-first), well before the full history is present.
- **SC-004**: An interrupted-and-restarted mirror re-fetches zero already-stored activities.
- **SC-005**: When the read budget is exhausted, the mirror resumes automatically after the
  window resets with no operator intervention, and reports the pause and its expected end
  while waiting.
- **SC-006**: 100% of agent reads are served from the local mirror; zero agent reads contact
  Strava directly.
- **SC-007**: No partially-enriched activity is ever returned to an agent; activities the
  frontier has not reached return the "not yet synced" signal 100% of the time.
- **SC-008**: After backfill, a poll detects a newly added or back-dated-within-window
  activity by the next cadence (or immediately when nudged) and never alters existing
  records.
- **SC-009**: A training summary for a given period and optional sport matches the
  underlying mirrored activities exactly.
- **SC-010**: No credential or secret ever appears in logs or outside the local data
  directory.

## Assumptions

- **Single user, local only**: the mirror runs on one machine for one Strava account; the
  serving interface is loopback-only with no added network authentication layer. (PRD §8.2)
- **Read-only, insert-only**: no write operations to Strava; edits/deletes on Strava are not
  reconciled; the mirror grows by insertion only. (PRD §2, §3)
- **No real-time push**: no webhooks; freshness comes from the 12-hour poll plus on-demand
  nudge. A poll look-back of 14 days is assumed sufficient to catch back-dated uploads;
  uploads back-dated beyond that window are not guaranteed to be caught. (PRD §2, §6.1)
- **Scope boundaries**: no discovery of other athletes, no clubs, no public segment
  discovery (bounding-box search), no per-encountered-segment upgrade crawl, and no
  GPX/TCX route/activity file export. (PRD §3)
- **Backfill duration is bounded by Strava's rate limits**, not by the tool; a full history
  backfill may legitimately take hours or days, during which the mirror is partially
  populated but already useful. (PRD §6, PLAN slice 8)
- **Initial seed credentials may be under-scoped**; the deliberate authorization step is
  what mints full-read credentials, and the server checks scope before serving. (PRD §8)
- **The queryable form is a rebuildable projection of the raw store**; the raw store is the
  durable backup of record. (PRD §4)
- **Stream data is the dominant volume** and is stored per stream type with metadata rather
  than exploded per sample. (Constitution IV)
