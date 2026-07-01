# Implementation Plan: Observability & Audit Logging

**Branch**: `006-observability-audit-logging` | **Date**: 2026-06-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-observability-audit-logging/spec.md`

## Summary

Make failures visible and add a structured, append-only audit trail across the three runtime
surfaces (MCP `serve`, the sync worker, and the `dashboard`) **without** breaking any existing
invariant. Two coordinated pieces:

1. **Operational logging** — instrument the currently-silent layers (the Strava HTTP client and
   the MCP tool dispatch), raise dashboard request logging to a visible level, give the worker's
   swallowed-error path real diagnostic context, add a startup config summary, make the log level
   env-configurable, and thread a **correlation id** through a logical operation so a tool call
   can be tied to the Strava calls it triggered.
2. **Audit trail** — a second, dedicated sink writing **newline-delimited JSON** (one event per
   line) to `./.logs/audit.log`, rotating like the main log, carrying three streams (`mcp`,
   `strava`, `dashboard`) with a request + response event each. The audit sink reuses the existing
   secret redaction and is **best-effort** (a sink failure never breaks the observed operation).

This is an **additive instrumentation** change. No schema change, no new runtime dependency, and
the audit trail is **files only** — nothing is written into the mirror DB, so the dashboard stays
read-only and the worker stays the single writer.

## Technical Context

**Language/Version**: Python 3.11+ (managed by `uv`)

**Primary Dependencies**: FastMCP (`streamable-http`), httpx, pydantic-settings — **no new deps**
(audit JSON uses stdlib `json`; rotation uses stdlib `logging.handlers.RotatingFileHandler`).

**Storage**: SQLite mirror unchanged. Audit data lives **only** in `./.logs/audit.log` (+ rotated
segments). No table, no migration.

**Testing**: pytest (offline; real temp SQLite in WAL mode for DB-layer tests; recorded fixtures
for Strava; no live API). New tests assert log/audit emission, redaction, correlation, and
best-effort behavior.

**Target Platform**: Local single-user loopback service (Linux)

**Project Type**: Single project — CLI + loopback MCP server + background worker + read-only dashboard

**Performance Goals**: Logging must not regress the hot read path. Per-request Strava detail sits
at DEBUG; the audit write is a single buffered append per event; a sink error is caught, never
retried inline.

**Constraints**: Loopback-only; read-only scopes; no secret in any sink; audit is file-only
(never the mirror DB); no live-API calls in tools or tests; no new external dependency.

**Scale/Scope**: Concentrated in `logging.py` (extended) + a new `audit.py` module, with small
edits at four instrumentation points (`client/http.py`, `mcp/server.py`, `dashboard/server.py`,
`sync/orchestrator.py`), plus `config.py` (two new settings) and docs. ~6 source files + tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Code Quality & Architectural Integrity** — ✅ **Preserved.** Module separation holds: the
  audit/logging concern lives in `logging.py` + a new sibling `audit.py`; instrumentation is added
  at each layer's own boundary, not by cross-module reach-in. **MCP tools remain pure DB readers**
  — the tool wrapper only times/records around the existing call, it does not add a network call.
  **Vocabulary discipline**: log/audit strings use the canonical terms (backfill, frontier, poll,
  enrichment, fully synced, raw store); avoided synonyms (import/refresh-as-sync/cache) stay out.
- **II. Testing Standards (NON-NEGOTIABLE)** — ✅ Honored. Each acceptance criterion maps to a test
  (Strava error logged, tool error logged, swallowed worker error has context, redaction holds in
  both sinks, audit line is parseable JSON with the four mandatory fields, audit-sink failure does
  not break the request, correlation id ties events). No live Strava; existing fixture/temp-SQLite
  patterns reused. Redaction is regression-first (extend `tests/unit/test_log_redaction.py`).
- **III. User Experience Consistency** — ✅ **Strengthened.** "Observability is part of UX" and
  "Actionable failure modes" are direct constitution rules; this feature advances both. Tool return
  shapes are **unchanged** — instrumentation wraps tools without altering their outputs or the
  `not yet synced` / `not found` sentinels.
- **IV. Performance & Rate-Limit Discipline** — ✅ Respected. Single-writer/WAL untouched (audit is
  file-only). Read tools take no write lock. Per-request Strava logging is DEBUG so the default log
  stays readable during backfill; rate-limit accounting is read from the existing `RateLimitBudget`
  snapshot, not re-derived.
- **Technology & Security Constraints** — ✅ Honored, **one doc nit noted.** No secret reaches either
  sink (redaction applied to both, incl. structured audit fields). Loopback unchanged; no new dep.
  The constitution's *Logging* clause still names the old path `./.database/strava-mcp.log`; the code
  already moved logs to `./.logs/` (commit `0446a26`). This feature follows the **current** `./.logs/`
  location and adds `./.logs/audit.log` beside it. This is a pre-existing wording drift, not introduced
  here; a PATCH wording fix to the clause is proposed (non-blocking, see Complexity Tracking).

**Gate result**: PASS. No architectural exception required. One optional PATCH constitution wording
fix (log path) is proposed but not load-bearing for this feature.

## Project Structure

### Documentation (this feature)

```text
specs/006-observability-audit-logging/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (audit event schema)
├── quickstart.md        # Phase 1 output (validation guide)
├── contracts/           # Phase 1 output
│   ├── audit-events.md      # JSONL event contract (3 streams, fields, examples)
│   └── logging-api.md       # internal logging/audit module surface + log-level config
└── checklists/
    └── requirements.md  # from /speckit-specify
```

### Source Code (repository root)

```text
strava_mcp/
├── logging.py                  # EDIT: env-configurable level; export a shared redaction
│                               #       helper reused by the audit sink; keep dual human sink.
├── audit.py                    # NEW: AuditLogger — JSONL rotating sink + emit(stream, event,
│                               #       req_id, **fields); redaction-scrubbed; best-effort
│                               #       (never raises); correlation-id helper (contextvar).
├── config.py                   # EDIT: add strava_log_level (default "INFO") and
│                               #       strava_audit_path (default "./.logs/audit.log").
├── client/
│   └── http.py                 # EDIT: log request(DEBUG)/response(INFO)/error(WARN|ERROR) with
│                               #       method/path/status/latency; emit strava audit req+resp
│                               #       (+ rate-limit snapshot); no token/headers logged.
├── mcp/
│   └── server.py               # EDIT: wrap each registered tool (time + log + mcp audit
│                               #       req+resp, sanitized args, correlation id); startup
│                               #       config summary line. Tools stay pure readers.
├── dashboard/
│   └── server.py               # EDIT: raise per-request logging to INFO (method/path/status/
│                               #       latency/client); emit dashboard audit event; startup
│                               #       config summary. Still read-only over the mirror.
└── sync/
    └── orchestrator.py         # EDIT: _run_with_cooldown logs swallowed non-rate-limit errors
                                #       with exception context (log.exception/exc_info).

tests/
├── unit/
│   ├── test_log_redaction.py   # EDIT: assert redaction applies to audit JSON fields too.
│   ├── test_audit.py           # NEW: emit() writes one parseable JSON line w/ 4 mandatory
│   │                           #       fields; rotation; redaction; best-effort on bad sink.
│   └── test_config.py          # EDIT: defaults for strava_log_level / strava_audit_path.
├── contract/
│   └── test_strava_client_logging.py  # NEW: non-2xx → WARN/ERROR line + strava audit resp.
└── dashboard/
    └── test_dashboard_audit.py # NEW: a page load emits one dashboard audit event.

.env.example                    # EDIT: document STRAVA_LOG_LEVEL / STRAVA_AUDIT_PATH.
README.md                       # EDIT: Logging section — human log + audit.log, levels, fields.
.specify/memory/constitution.md # EDIT (optional PATCH): Logging clause path → ./.logs/ + audit.log.
```

**Structure Decision**: Single-project layout (existing). One new module (`audit.py`) keeps the
structured-audit concern cohesive and separate from the human-log plumbing in `logging.py`, mirroring
the existing one-concern-per-module style. All other changes are localized edits at each layer's own
instrumentation boundary.

## Complexity Tracking

> No constitution violations requiring justification. The only governance note is an **optional PATCH**
> wording fix to the *Logging* clause (old `./.database/strava-mcp.log` path → current `./.logs/` +
> the new `audit.log`); it documents reality rather than changing a principle, so it is not an
> architectural exception and this table is intentionally otherwise empty.
