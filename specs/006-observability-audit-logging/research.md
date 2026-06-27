# Phase 0 Research: Observability & Audit Logging

All Technical Context unknowns are resolved below. No live-Strava dependency; no new package.

## R1 — Audit sink: JSONL file vs SQLite audit table

**Decision**: Structured **JSONL file** (`./.logs/audit.log`, rotating), one JSON object per line.

**Rationale**:
- The dashboard is constitutionally **read-only over the mirror** and the **worker is the single
  writer** of the mirror DB. An audit *table in the mirror* written from the dashboard (and from the
  worker, and from the MCP process) would introduce multiple concurrent writers and break that
  invariant. A separate file sink sidesteps the writer model entirely.
- JSONL is append-only, greppable, trivially parseable line-by-line, and rotates with the stdlib
  `RotatingFileHandler` already used for the human log — zero new dependency.
- Confirmed with the requester (spec Assumptions).

**Alternatives considered**:
- *Separate `audit.db` SQLite file*: queryable, but adds schema + a writer + retention code for no
  required query path (a dashboard `/audit` viewer is explicitly out of scope). YAGNI per Constitution.
- *Audit rows in the mirror DB*: rejected — violates single-writer / read-only-dashboard invariants.

## R2 — How to emit JSONL safely (formatting + rotation + best-effort)

**Decision**: A dedicated `logging.Logger` named `strava_mcp.audit` with `propagate=False` and a
single `RotatingFileHandler` whose formatter emits **only** `record.getMessage()` (the pre-serialized
JSON string). A thin `AuditLogger.emit(stream, event, *, req_id, **fields)` builds the dict, adds
`ts`/`stream`/`event`/`req_id`, `json.dumps(..., separators=(",",":"), default=str)`, and logs it.
The whole `emit` body is wrapped in `try/except Exception: pass` (best-effort).

**Rationale**:
- Reusing the `logging` machinery gives rotation, thread-safe writes (the handler holds a lock so
  lines are not interleaved), and the same redaction-filter mechanism for free.
- A JSON-only formatter keeps each line a self-contained record (FR-014, SC-005).
- `default=str` makes serialization total (no event is dropped because a value isn't JSON-native).
- Best-effort wrapping satisfies FR-016/SC-004 (a sink failure never breaks the observed operation).

**Alternatives considered**: hand-rolled `open(..., "a")` writes (loses rotation + locking);
third-party structured loggers like `structlog` (new dependency, disallowed).

## R3 — Redaction reuse across both sinks (including structured fields)

**Decision**: Keep the existing regex `_scrub`/`RedactionFilter` in `logging.py` as the single source
of truth. Attach the same `RedactionFilter` to the audit handler so the **final serialized JSON line**
is scrubbed (a token that slipped into any field value is caught at the formatted-message level). Also
expose `scrub(text)` for callers that want to pre-sanitize a specific field.

**Rationale**: One redaction implementation, applied to both sinks (FR-015). Scrubbing the serialized
line is a belt-and-suspenders catch-all over per-field sanitization. The existing patterns already
cover bearer headers, `access_token`/`refresh_token`/`client_secret`/`code` JSON fields, and long hex
blobs — exactly the secrets in scope.

**Alternatives considered**: a separate audit-only redactor (divergence risk); structured-field
allowlisting only (misses a secret embedded in an unexpected field — weaker than scrubbing the line).

## R4 — Correlation id propagation across layers

**Decision**: A module-level `contextvars.ContextVar[str | None]` in `audit.py`, with a
`correlation_scope()` context manager that sets a short token (`secrets.token_hex(4)`) on enter and
resets it on exit. The MCP tool wrapper opens a scope per tool call; the Strava client reads the
current value (falling back to its own per-call id) so worker-side calls during that logical operation
share the id. Each surface that originates work (a dashboard request, a worker poll/backfill page) may
open its own scope.

**Rationale**:
- `ContextVar` is thread-safe and async-safe and does **not** bleed across threads (each thread sees
  its own value), satisfying the concurrency edge case. The worker runs on its own thread; the
  dashboard serves on per-request threads.
- `token_hex(4)` (8 hex chars) is enough to disambiguate concurrent operations in a single-user
  service and keeps log lines short.

**Alternatives considered**: passing an explicit `req_id` argument through every call site (invasive,
touches signatures across modules); thread-local storage (works but `ContextVar` is the modern,
async-safe primitive and is stdlib).

**Caveat documented**: MCP tools are pure DB readers and issue no Strava calls, so correlation is
*intra-operation*, never across a tool→Strava boundary. A worker logical unit (one enrichment / one
page) opens a scope so its Strava calls share an id; a dashboard request and an MCP tool call each
group their own events. There is no cross-process correlation, and none is needed. The audit trail
still independently records every `strava` call.

## R5 — Wrapping MCP tools without changing their contracts

**Decision**: In `register_tools`, wrap each tool callable with a small decorator
`instrument(name)(fn)` applied **before** `@mcp.tool`. The wrapper: opens a `correlation_scope`, emits
the `mcp` request audit event (tool name + sanitized args), times the call, emits the response event
(ok/error + duration), logs at INFO (ok) / ERROR (exception), and re-raises unchanged so FastMCP's
own error handling and the tool's return shape are untouched.

**Rationale**: Tool outputs and the `not yet synced`/`not found` sentinels must not change
(Constitution III). A transparent wrapper around the existing closure is the least-invasive hook and
needs no FastMCP-internal API. Args are summarized (names + scalar values + collection sizes), then
passed through redaction — never dumped verbatim.

**Alternatives considered**: FastMCP middleware (couples to FastMCP version internals; the closure
wrapper is simpler and version-stable); editing each tool body (repetition across ~16 tools).

## R6 — Strava client instrumentation point

**Decision**: Instrument `StravaClient._request` (the single chokepoint all `get()` calls pass
through). Record start time; on response log `method path -> status (Nms)` at INFO and emit the
`strava` audit request+response (method, path, sanitized query, status, latency, and the
`rate_limiter.snapshot()` budget when a limiter is attached); on `status >= 400` log WARNING (4xx) or
ERROR (5xx) with the parsed fault `message`; on transport exception log ERROR and emit a response
event with `error`. Never log headers or the bearer token.

**Rationale**: One chokepoint covers every endpoint and keeps the mapping to `_map_fault` (which
already parses the Strava fault message) in one place. The rate-limit snapshot is exactly the
`RateLimitBudget.snapshot()` shape already persisted to `sync_state`, so the audit reuses it.

**Alternatives considered**: instrumenting each call site (none exist beyond `get`); an httpx event
hook (less control over our fault mapping + audit shape).

## R7 — Log level configuration & startup summary

**Decision**: Add `strava_log_level: str = "INFO"` and `strava_audit_path: str = "./.logs/audit.log"`
to `Settings`. `setup_logging` parses the level name via `logging.getLevelName` (invalid → INFO with a
warning). `serve` and `dashboard` each emit one INFO startup line summarizing bind host/port, db path,
log path, audit path, and effective level.

**Rationale**: Env-driven config matches the existing pydantic-settings pattern; a single startup line
(FR-006) lets the operator confirm the effective configuration at a glance. No secret appears in it.

**Alternatives considered**: a `--log-level` CLI flag (env is consistent with the rest of config and
needs no argparse change); per-module levels (overkill for a single-user service).

## R8 — Worker swallowed-error visibility

**Decision**: In `Orchestrator._run_with_cooldown`, replace `log.warning("%s failed: %s", label, exc)`
with `log.exception("%s failed; skipping", label)` (or `log.error(..., exc_info=exc)`), so the
traceback and exception type are captured while the skip-and-continue behavior is unchanged.

**Rationale**: FR-005/SC-001 — the operator must be able to diagnose a swallowed enrichment/bootstrap
failure, not just see that one occurred. Behavior (cool down on rate-limit, skip otherwise) is
preserved; only the log richness changes.

**Alternatives considered**: re-raising (would abort backfill — rejected, violates the resilient
enrichment design); leaving as-is (fails the visibility goal).

## Summary of decisions

| # | Topic | Decision |
|---|-------|----------|
| R1 | Audit sink | JSONL rotating file `./.logs/audit.log` (no DB, no new dep) |
| R2 | Emit mechanism | `strava_mcp.audit` logger + JSON-only formatter; best-effort `emit()` |
| R3 | Redaction | Single `RedactionFilter`/`scrub` reused on both sinks + serialized line |
| R4 | Correlation | `contextvars` id via `correlation_scope()`; thread-safe, no bleed |
| R5 | MCP tools | Transparent `instrument()` wrapper before `@mcp.tool`; contracts unchanged |
| R6 | Strava client | Instrument `_request` chokepoint; reuse `_map_fault` + budget snapshot |
| R7 | Config | `STRAVA_LOG_LEVEL` + `STRAVA_AUDIT_PATH`; one startup summary line |
| R8 | Worker | `log.exception` on swallowed non-rate-limit failures |
