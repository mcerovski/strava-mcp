# Feature Specification: Observability & Audit Logging

**Feature Branch**: `006-observability-audit-logging`

**Created**: 2026-06-25

**Status**: Draft

**Input**: User description: "Improve logging so it is easy to know when something is not working or breaks, and create a dashboard logging/audit so each user request/response is logged, each Strava request/response is logged, and each user interaction with the dashboard is logged."

## User Scenarios & Testing *(mandatory)*

The actors are: the **operator** (the single person who runs `serve`/`dashboard` and reads the logs to keep the service healthy), the **agent** (an AI/MCP client issuing tool calls), and the **dashboard user** (the operator browsing the read-only web UI).

### User Story 1 - Operator sees when something breaks (Priority: P1)

The operator runs the service for hours or days (a multi-year backfill is bounded by Strava's rate limit). When a Strava call fails, a token can't refresh, an MCP tool errors, or the worker thread dies, the operator must be able to open the human-readable log and immediately see *what* broke, *where*, and *why* — without attaching a debugger or adding print statements.

**Why this priority**: This is the core of the request ("easy to know when something is not working or breaks"). Today the Strava HTTP client and the MCP tool layer emit no logs at all, so the most common failure points are invisible. This story delivers value on its own even without the structured audit trail.

**Independent Test**: Force each failure class against a recorded/offline fixture — a non-2xx Strava response, a raised tool error, a swallowed worker error, a missing-scope startup — and confirm each produces a log line at an appropriate severity (WARNING/ERROR) that names the operation and the cause, with no secret values present.

**Acceptance Scenarios**:

1. **Given** the Strava API returns a non-success response, **When** the worker makes that call, **Then** a single log line records the method, path, HTTP status, and the parsed Strava fault message at WARNING (client errors) or ERROR (server errors), and the bearer token is never present.
2. **Given** an MCP tool raises an exception, **When** an agent invokes it, **Then** a log line records the tool name, the failure, and how long it ran, at ERROR severity.
3. **Given** the worker hits a non-rate-limit failure that it chooses to skip, **When** that happens, **Then** the log records the operation label *and* the underlying exception with enough context (stack/trace) to diagnose it — not just a one-line summary.
4. **Given** the operator starts `serve` or `dashboard`, **When** the process boots, **Then** a startup line summarizes the effective configuration (bind host/port, database path, log path, log level) so the operator can confirm what the process is actually using.
5. **Given** the operator wants more or less detail, **When** they set the log-level configuration value, **Then** the process honors it (e.g. DEBUG surfaces every outbound Strava request; WARNING suppresses routine INFO narration).

---

### User Story 2 - Complete audit trail of every interaction (Priority: P1)

The operator (or a later reviewer) needs an append-only, machine-readable record of everything the system did on their behalf: every agent tool request and its response, every Strava API request and its response, and every dashboard interaction. This record is separate from the human-readable log, one structured event per line, so it can be filtered, counted, and correlated after the fact.

**Why this priority**: This is the explicit second half of the request ("each user request/response logged, each Strava request/response logged, each user interaction with the dashboard logged"). It is co-equal P1 with Story 1: the operator asked for both visibility *and* an audit trail.

**Independent Test**: Drive one agent tool call, one Strava call, and one dashboard page load against offline fixtures; confirm the audit file gains exactly the expected request/response events for each of the three streams, each a single parseable structured record carrying a timestamp, stream label, event type, and a correlation id, with no secrets.

**Acceptance Scenarios**:

1. **Given** an agent invokes a tool, **When** the tool runs, **Then** the audit trail records a `mcp` request event (tool name, sanitized argument summary, correlation id) and a corresponding response event (outcome ok/error, duration, correlation id).
2. **Given** the worker calls Strava, **When** the call completes (success or failure), **Then** the audit trail records a `strava` request event (method, path, sanitized query summary) and a response event (HTTP status, latency, and rate-limit/budget information), sharing a correlation id with the request.
3. **Given** a dashboard user loads any page, **When** the request is served, **Then** the audit trail records a `dashboard` event (method, path, sanitized query, response status, latency, client address).
4. **Given** any audit event is written, **When** it is read back, **Then** it is a single self-contained structured line carrying at minimum a UTC timestamp, the stream label, the event type, and a correlation id.
5. **Given** the worker performs one logical operation (e.g. enriching a single activity, which issues several Strava calls), **When** the operator inspects the audit trail, **Then** those Strava events share one correlation id so the operation's calls read as a group; an MCP tool call and a dashboard request each group their own request/response events under their own id.

---

### User Story 3 - Secrets and stability guarantees hold under logging (Priority: P1)

Adding logging must not leak credentials and must not destabilize the service. No bearer token, access/refresh token, client secret, or OAuth code may ever appear in either the human log or the audit trail. A failure inside the logging path must never break the request or call it was observing.

**Why this priority**: These are non-negotiable invariants from the project constitution (no secrets logged; the dashboard stays read-only over the mirror; the worker stays the single writer of the mirror). A logging feature that violates them is worse than no feature. Treated as P1 because it gates the other two stories.

**Independent Test**: Inject a token-bearing string and a secret-shaped value through each logging entry point and confirm they are redacted in both sinks; force the audit sink to fail (e.g. unwritable path) and confirm the observed request/call still completes normally.

**Acceptance Scenarios**:

1. **Given** a message or audit field contains a token-shaped or secret-shaped value, **When** it is logged, **Then** the emitted line shows a redaction placeholder instead of the secret, in both the human log and the audit trail.
2. **Given** the audit sink cannot be written (path unwritable, disk error, serialization error), **When** an event would be recorded, **Then** the originating tool call, Strava call, or dashboard request still completes normally and the failure is swallowed.
3. **Given** the audit trail is enabled, **When** the dashboard serves requests, **Then** the mirror database is still only read (never written) and the sync worker remains the single writer of the mirror — the audit trail is file-based and does not write the mirror.

---

### Edge Cases

- **Large or sensitive arguments**: Tool/query arguments that are large or could embed identifiers are summarized (e.g. key names, sizes, ids) rather than dumped verbatim, and are passed through redaction.
- **High-volume DEBUG**: With DEBUG enabled during a long backfill, per-request Strava logging can be voluminous; routine request-level detail lives at DEBUG so the default level stays readable, while the audit trail (always-on, structured) is the durable record.
- **Log rotation**: The audit file rotates like the main log so neither grows unbounded; events that roll into a rotated segment remain valid standalone lines.
- **Concurrency**: Dashboard requests are served on multiple threads and the worker runs on its own thread; concurrent writers to the audit sink must each produce intact, non-interleaved lines.
- **Correlation across threads**: A correlation id set for one logical operation must not bleed into an unrelated concurrent operation on another thread.
- **Missing/!writable log directory**: If the log directory does not exist it is created; if it cannot be created or written, the process still runs and the operator is not blocked.
- **HEAD / static-asset / 404 dashboard requests**: These are still interactions and are audited (or consciously classified), not silently dropped.
- **Expected rate-limit responses**: A `429` / budget-exhaustion response drives the deterministic COOLDOWN (it is expected, not a defect), so it is logged at INFO/DEBUG with the cooldown target — not at WARNING/ERROR — keeping the failure signal (SC-001) clean.

## Requirements *(mandatory)*

### Functional Requirements

**Operational logging (failure visibility)**

- **FR-001**: The system MUST log every outbound Strava API request at a verbose (DEBUG) level and every Strava response — with method, path, HTTP status, and latency — at an informational level.
- **FR-002**: The system MUST log Strava non-success responses and request exceptions at WARNING (client-side, 4xx) or ERROR (server-side/5xx/transport) severity, including method, path, status, and the parsed Strava fault message.
- **FR-003**: The system MUST log every MCP tool invocation with the tool name, a sanitized argument summary, the outcome (success or failure), and the duration; failures MUST be logged at ERROR severity.
- **FR-004**: The system MUST log every dashboard request at a visible (informational) severity with method, path, response status, and latency (raising it above the current effectively-silent level).
- **FR-005**: The system MUST log swallowed non-rate-limit worker failures with the operation label *and* diagnostic context (exception type/message and traceback), not only a one-line summary.
- **FR-006**: The system MUST emit a startup configuration summary for `serve` and `dashboard` (bind host/port, database path, log path, effective log level).
- **FR-007**: The system MUST allow the operator to configure the log level via an environment setting (default INFO).
- **FR-008**: The system MUST attach a correlation id to each logical operation so the records it produces are grouped — e.g. all Strava calls made while enriching one activity (detail + laps + zones + streams + segment efforts) share one id, and a tool call's request/response pair shares one id. MCP tools are pure DB readers and do not themselves call Strava (Constitution I), so correlation groups events *within* an operation, not across a tool→Strava boundary.

**Audit trail**

- **FR-009**: The system MUST write a structured, machine-readable audit trail — one self-contained event per line — to a dedicated sink separate from the human-readable log.
- **FR-010**: The audit sink path MUST be configurable and MUST rotate (size-bounded with retained prior segments) like the main log.
- **FR-011**: The system MUST record, in the audit trail, both a request event and a response event for each agent tool call (stream `mcp`): tool name, sanitized argument summary, correlation id, and on response the outcome and duration.
- **FR-012**: The system MUST record, in the audit trail, both a request event and a response event for each Strava API call (stream `strava`): method, path, sanitized query summary, correlation id, and on response the HTTP status, latency, and available rate-limit/budget information.
- **FR-013**: The system MUST record, in the audit trail, each dashboard interaction (stream `dashboard`): method, path, sanitized query, response status, latency, and client address.
- **FR-014**: Every audit event MUST carry at minimum a UTC timestamp, the stream label, the event type, and a correlation id.

**Safety invariants**

- **FR-015**: The system MUST NOT write any secret (bearer token, access token, refresh token, client secret, OAuth code) to the human log or the audit trail; existing redaction MUST be applied to both sinks and to structured audit fields.
- **FR-016**: A failure inside the audit/logging path (unwritable sink, serialization error) MUST NOT propagate to or break the tool call, Strava call, or dashboard request being observed.
- **FR-017**: The audit trail MUST be file-based only; the dashboard MUST remain read-only over the mirror database and the sync worker MUST remain the single writer of the mirror — no audit data is written into the mirror database.
- **FR-018**: The feature MUST add no new external runtime dependencies and MUST be fully testable offline/deterministically (no live Strava access).

### Key Entities *(include if feature involves data)*

- **Audit event**: One observed interaction. Common attributes: UTC timestamp, stream (`mcp` | `strava` | `dashboard`), event type (request | response | interaction), correlation id. Stream-specific attributes: tool name + argument summary + outcome + duration (`mcp`); method + path + query summary + status + latency + rate-limit info (`strava`); method + path + query + status + latency + client address (`dashboard`).
- **Correlation id**: A short opaque identifier grouping the events of one logical operation across layers; scoped so concurrent operations do not share one.
- **Log sinks**: Two destinations — the existing human-readable log (`strava-mcp.log`) and a new structured audit log (`audit.log`) — both rotating and both secret-redacted.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For each of the four common failure classes (Strava non-success, tool exception, swallowed worker error, missing-scope startup), an operator reading only the human log can identify the failing operation and its cause in a single line — verified by a test per class.
- **SC-002**: 100% of agent tool calls, Strava API calls, and dashboard requests produce their expected audit events — no interaction type is silently unaudited.
- **SC-003**: Zero secrets appear in either sink across the redaction test suite (token-shaped and secret-shaped inputs injected at every entry point are redacted in 100% of cases).
- **SC-004**: Inducing an audit-sink failure leaves 100% of observed tool calls, Strava calls, and dashboard requests completing successfully (no observed-operation breakage from logging).
- **SC-005**: Every line in the audit trail is independently parseable as a structured record and carries the four mandatory fields (timestamp, stream, event, correlation id); a parser reads back 100% of emitted lines without error.
- **SC-006**: Given one worker operation (e.g. enriching a single activity, which issues several Strava calls), an operator can reconstruct that operation's full set of Strava calls from the shared correlation id; a dashboard request and an MCP tool call each likewise group their own request/response events under one id.
- **SC-007**: The default-level human log during a normal poll remains readable (routine per-request Strava detail does not appear unless the level is lowered to DEBUG).

## Assumptions

- "User request/response" in the original request maps to **agent/MCP tool calls** (the agent is the consumer of the MCP surface); "user interaction with the dashboard" maps to **dashboard HTTP requests**; "Strava request/response" maps to the worker's outbound API calls. These are the three audit streams.
- The audit trail is **structured JSONL files** (one JSON object per line) at `./.logs/audit.log`, chosen over a queryable SQLite audit table to preserve the mirror's read-only/single-writer invariants and avoid added schema. (Confirmed with the requester.)
- A **dashboard viewer page** for the audit trail, exporting/shipping logs to external systems, and metrics/Prometheus-style instrumentation are **out of scope** for this feature.
- The existing redaction mechanism is sound and will be reused/extended rather than replaced.
- Default log level is INFO; default audit path sits alongside the existing log under `./.logs/`.
- Single-user, loopback-only deployment continues to hold; there is no multi-tenant access control on the logs beyond filesystem permissions.
- Rotation policy for the audit log mirrors the existing main-log policy (size-bounded with a small number of retained segments) unless the operator configures otherwise.
