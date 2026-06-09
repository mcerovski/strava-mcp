# Feature Specification: Remove Comments & Kudos for Faster Sync

**Feature Branch**: `003-remove-comments-kudos`

**Created**: 2026-06-09

**Status**: Draft

**Input**: User description: "regardles of previous analysis i want to optimize api calls so activities sync faster. I want to remove comments and kudos from this project for faster sync regarding api limits. new optimization should not break currently running servers. nor keep any data regarding kudos and comments or show them on the dashboard complere removal nothing regarding those two should stay in the app"

## Overview

Each activity is currently made visible only after a fixed unit of enrichment work that includes fetching its **comments** and **kudos**. Those two facets each cost one Strava read request per activity but add little value relative to the rate-budget they consume. This feature removes comments and kudos **entirely** — from fetching, storage, the agent (MCP) tool surface, and any user-facing display — so that every activity costs fewer read requests to sync. The result is faster backfill and poll cycles within the same Strava rate budget, with no comments/kudos data or controls remaining anywhere in the product.

## Clarifications

### Session 2026-06-09

- Q: How far does "complete removal" reach into raw/archived data? → A: B — purge served data (normalized `comments`/`kudos` tables, count columns, MCP tools, display) and stop writing new comments/kudos raw payloads, but preserve the existing append-only `raw_responses` archive and `detail_json` blobs (never served to agents/dashboard).
- Q: How should the existing database physically reach the purged state on upgrade? → A: A — full physical removal: drop the `comments` and `kudos` tables and rebuild `activities` to remove the `kudos_count`/`comment_count` columns, so upgraded and freshly-created databases are structurally identical.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Faster activity sync within the rate budget (Priority: P1)

As the operator running a sync, I want each activity to require fewer Strava read requests so that a backfill of my activity history completes in fewer rate-limit windows and fewer calendar days.

**Why this priority**: This is the entire motivation for the change. Cutting two of the per-activity requests is the largest single lever available without dropping data the dashboard actually shows. It delivers value on its own even before any cleanup of historical data.

**Independent Test**: Run a backfill against recorded fixtures and confirm that the per-activity enrichment unit issues fewer read requests than before (no comments and no kudos requests are made), while every activity still becomes visible once its remaining enrichment completes. Measure the reduction in total requests for a fixed activity count.

**Acceptance Scenarios**:

1. **Given** an unsynced activity, **When** the sync worker enriches it, **Then** no request is made for that activity's comments and no request is made for its kudos, and the activity becomes visible once its remaining enrichment data is present.
2. **Given** a backfill of N activities, **When** the run completes, **Then** the total number of Strava read requests is reduced by the count previously attributable to comments and kudos (two requests per enriched activity).
3. **Given** the rate budget is being tracked, **When** the worker syncs activities, **Then** more activities are enriched per rate-limit window and per day than before the change, for the same budget.

---

### User Story 2 - No comments or kudos anywhere in the product (Priority: P2)

As an agent (or operator) using the product, I should find no comments or kudos data, tools, fields, or display anywhere, so the product surface is consistent and reflects that these facets no longer exist.

**Why this priority**: The user explicitly requires complete removal — "nothing regarding those two should stay in the app." Without it, the surface would advertise capabilities that no longer have data behind them, which is misleading and violates the product's "no partial/fabricated results" expectation.

**Independent Test**: Inspect the agent tool surface, the stored data model, and the dashboard. Confirm there is no tool, field, table, count, label, or control referring to comments or kudos, and that no query path can return such data.

**Acceptance Scenarios**:

1. **Given** the agent tool surface, **When** it is listed, **Then** there is no tool for retrieving comments and no tool for retrieving kudos.
2. **Given** an activity's stored record, **When** it is read, **Then** it exposes no comments collection, no kudos collection, and no comment-count or kudos-count field.
3. **Given** the dashboard, **When** any activity (list or detail) is viewed, **Then** no comments and no kudos information or controls appear anywhere.
4. **Given** a search of the product's vocabulary (tool descriptions, labels, stored fields), **When** "comment" or "kudos" is sought, **Then** no references remain in active surfaces.

---

### User Story 3 - Safe upgrade of an already-running deployment (Priority: P3)

As an operator with an already-running server and an existing database that contains previously synced comments and kudos, I want to upgrade to the new build and have it run cleanly — without manual database surgery, crashes, or loss of access to my already-synced activities.

**Why this priority**: The user requires that the optimization "not break currently running servers." Existing deployments already hold comments/kudos data and were built around an enrichment definition that included them; the upgrade must be graceful.

**Independent Test**: Start from a database produced by the current (pre-change) build that contains activities with comments and kudos. Apply the new build, start it, and confirm it runs without error, that previously synced activities remain visible, and that no comments/kudos data or controls remain after the upgrade settles.

**Acceptance Scenarios**:

1. **Given** a database created by the previous build (with comments and kudos present), **When** the new build starts against it, **Then** the server starts successfully and serves previously synced activities without error.
2. **Given** that prior database, **When** the upgrade completes, **Then** any retained comments/kudos data is purged so none remains, consistent with "nothing regarding those two should stay."
3. **Given** an activity that was previously visible (fully synced) under the old enrichment definition, **When** it is read after upgrade, **Then** it remains visible and is not forced back into a "not yet synced" state by the removal.
4. **Given** a poll cycle after upgrade, **When** new activities are enriched, **Then** they follow the new, cheaper enrichment path with no comments/kudos requests.

---

### Edge Cases

- **Activity with existing comments/kudos rows**: after upgrade, those rows must be purged and never surfaced; reading the activity must not error on their absence.
- **Activity previously enriched using comments/kudos as a visibility gate**: removing those facets must not retroactively hide it. The visibility definition must be redefined so already-visible activities stay visible.
- **Agent that still calls the (now-removed) comments or kudos retrieval**: the request must fail predictably as an unknown operation, not return stale or fabricated data.
- **Mid-sync upgrade**: if a sync was in progress under the old build, restarting on the new build must resume on the new (cheaper) path without re-fetching already-stored activities and without requiring the removed facets.
- **Interrupted `activities` rebuild**: the table rebuild that drops the count columns must be atomic — an interruption mid-rebuild must leave the database in either the pre- or post-rebuild state, never a partial one, and must be safely re-runnable on next start.
- **Re-run on already-migrated database**: starting the new build against a database that has already been purged (or was created fresh) must be a no-op with no error.
- **In-flight rate-limit accounting**: removing two requests per activity must be reflected accurately in budget/progress reporting so throughput estimates stay correct.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST NOT request an activity's comments from Strava during any sync phase (backfill or poll).
- **FR-002**: The system MUST NOT request an activity's kudos from Strava during any sync phase.
- **FR-003**: The per-activity enrichment unit MUST be redefined to exclude comments and kudos, reducing per-activity read requests by exactly two while preserving all remaining facets.
- **FR-004**: An activity's visibility ("fully synced") MUST be determined without reference to comments or kudos, and the change MUST NOT cause any activity that was previously visible to become hidden.
- **FR-005**: The system MUST NOT store comments or kudos data in any **served** form going forward: no dedicated normalized tables, no promoted count fields, and no copies surfaced to readers. The append-only raw archive (`raw_responses`) and verbatim `detail_json` blobs, which are never served to agents or the dashboard, are exempt and retain prior payloads.
- **FR-006**: The agent (MCP) tool surface MUST NOT expose any tool for retrieving comments or kudos.
- **FR-007**: Activity records returned by tools MUST NOT include comments, kudos, comment-count, or kudos-count fields.
- **FR-008**: The dashboard MUST NOT display comments, kudos, or any count, label, or control derived from them, in either list or detail views.
- **FR-009**: Product vocabulary in active surfaces (tool names/descriptions, stored field names, dashboard labels) MUST contain no comments or kudos references.
- **FR-010**: Upgrading an existing deployment MUST NOT break it: the new build MUST start and serve against a database produced by the prior build without manual schema edits and without crashing on residual comments/kudos structures.
- **FR-011**: On upgrade, previously stored comments and kudos data in **served** structures MUST be physically removed: the `comments` and `kudos` normalized tables MUST be dropped, and the `activities` table MUST be rebuilt without the `kudos_count`/`comment_count` columns, so an upgraded database is structurally identical to a freshly-created one. Existing append-only `raw_responses` rows and `detail_json` blobs are preserved as the immutable durable backup and are out of scope for purging.

- **FR-012**: Checkpoint/resume MUST continue to work across the upgrade: a sync interrupted under the old definition MUST resume under the new one without re-fetching already-stored activities.
- **FR-013**: After the change, the `sync_status` request/budget counters (and the rate-limit accounting that feeds them) MUST reflect the reduced per-activity request count — i.e., they account for the four requests actually issued per enriched activity (detail + laps + zones + streams), with no phantom comments/kudos requests recorded.
- **FR-014**: A request for the removed comments/kudos capability MUST fail as an unknown/unsupported operation rather than returning stale, empty-as-if-real, or fabricated data.
- **FR-015**: The destructive upgrade (dropping tables, rebuilding `activities`) MUST be guarded so it runs only when the legacy comments/kudos structures are present, MUST be idempotent (safe to run repeatedly and a no-op on an already-migrated or freshly-created database), and MUST preserve all non-comments/kudos data on the rebuilt `activities` table.

### Key Entities *(include if feature involves data)*

- **Activity (enriched record)**: the stored representation of a Strava activity. After this change its enrichment unit and stored fields no longer include comments, kudos, comment-count, or kudos-count. Its visibility is gated only by its remaining required facets.
- **Comments (removed)**: previously a per-activity collection of social comments. Removed from fetching, storage, tools, and display; existing data is purged.
- **Kudos (removed)**: previously a per-activity collection of kudos givers (and an associated count). Removed from fetching, storage, tools, and display; existing data is purged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Per-activity sync cost drops by exactly two read requests (from six to four for a fully-faceted activity), a ~33% reduction in per-activity request count.
- **SC-002**: For a fixed daily read budget, the number of activities fully synced per day increases by ≈50% (at least 45%) compared to before the change — the 900-request worker budget covers ~149 → ~223 fully-synced activities/day once two requests per activity are removed.
- **SC-003**: A representative backfill (e.g., 1,000 activities) completes in fewer rate-limit windows and fewer calendar days than before, with the request total reduced by the comments+kudos count.
- **SC-004**: An audit of the agent tool surface, stored data model, and dashboard returns zero comments/kudos tools, fields, tables, counts, labels, or controls.
- **SC-005**: 100% of activities that were visible before the change remain visible after it; none are pushed back to "not yet synced" by the removal.
- **SC-006**: An existing-deployment upgrade test starts cleanly against a prior-build database, serves previously synced activities, and leaves zero residual comments/kudos data — with no manual database steps required.
- **SC-007**: After upgrade, the structure of an upgraded database (tables and columns) is identical to that of a freshly-created database — no `comments`/`kudos` tables and no count columns in either.

## Assumptions

- **Complete removal targets served surfaces, not the immutable raw archive.** Per the Session 2026-06-09 clarification, removal covers the dedicated comments/kudos normalized stores, the promoted comment-count / kudos-count fields, the MCP tools, and all display — even the counts that arrive "for free." The append-only `raw_responses` archive and verbatim `detail_json` blobs are preserved (they are never served to agents or the dashboard).
- **A normal stop → upgrade → start cycle is acceptable.** "Not break currently running servers" is interpreted as: the new build runs cleanly against a database produced by the prior build, with no manual schema surgery and no data loss for non-comments/kudos data. Zero-downtime hot-swapping of a live process mid-request is not assumed to be required.
- **The dashboard does not currently surface comments/kudos.** Initial inspection found no dashboard usage of these facets, so dashboard work is expected to be verification (and removal of any incidental label) rather than feature removal. This will be confirmed during planning.
- **The two removed requests are the comments and kudos facet requests only.** Other facets (detail, laps, zones, streams) remain part of enrichment and are unchanged by this feature.
- **The removed agent tools are acceptable to drop.** Any agent previously calling the comments or kudos retrieval tools will need to stop; this is accepted as the intended consequence of complete removal.

## Dependencies & Constraints

- **Constitution amendment required.** The project constitution (Principle III, "User Experience Consistency") currently defines a fully-enriched activity as `detail + laps + comments + kudos + zones + streams` and mandates "stable schemas" for the tool surface. This feature redefines enrichment to exclude comments and kudos and removes two tools, so the constitution (and any canonical vocabulary doc, e.g. CONTEXT.md) MUST be amended in the same change to remain authoritative.
- **Rate-limit discipline unchanged.** The deterministic cooldown behavior and budget tracking (Principle IV) remain in force; only the per-activity request count changes.
- **Single-writer / dual-write integrity preserved for remaining facets.** Removing comments/kudos MUST NOT weaken the dual-write or visibility guarantees for the facets that remain.
