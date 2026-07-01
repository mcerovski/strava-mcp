---
description: "Task list for Observability & Audit Logging"
---

# Tasks: Observability & Audit Logging

**Input**: Design documents from `/specs/006-observability-audit-logging/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/audit-events.md, contracts/logging-api.md, quickstart.md

**Tests**: INCLUDED — Constitution II (Testing Standards) is NON-NEGOTIABLE: every acceptance
criterion maps to an offline, deterministic test (no live Strava).

**Organization**: Tasks grouped by user story. All three stories are P1; the shared
logging/audit foundation (Phase 2) blocks all of them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 (failure visibility), US2 (audit trail), US3 (secrets & stability)
- Exact file paths included in each task.

## Path Conventions

Single project: source under `strava_mcp/`, tests under `tests/` at repo root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration surface the rest of the feature reads.

- [X] T001 [P] Add `strava_log_level: str = "INFO"` and `strava_audit_path: str = "./.logs/audit.log"` settings to `strava_mcp/config.py` (alongside the existing `strava_log_path`).
- [X] T002 [P] Document `STRAVA_LOG_LEVEL` and `STRAVA_AUDIT_PATH` (with defaults) in `.env.example`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The logging/audit primitives every story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Extend `strava_mcp/logging.py`: make `setup_logging` accept a level name or int (invalid name → INFO + one warning); promote the private `_scrub` to a public `scrub(text)` reused by the audit sink; keep `RedactionFilter` and patterns unchanged. (per contracts/logging-api.md)
- [X] T004 [P] Create `strava_mcp/audit.py`: `setup_audit(audit_path)` (one `RotatingFileHandler` 2MB×3, JSON-only formatter, `RedactionFilter` attached, `propagate=False`, idempotent, creates parent dir); `emit(stream, event, *, req_id=None, **fields)` building `{ts, stream, event, req_id, **fields}` → `json.dumps(..., separators=(",",":"), default=str)`, **wrapped in try/except so it never raises**; `correlation_scope()` contextmanager + `current_req_id()` over a module `ContextVar` (id = `secrets.token_hex(4)`). (per data-model.md + contracts/logging-api.md)
- [X] T005 [P] Add a sanitizer helper in `strava_mcp/audit.py` (e.g. `summarize_args(mapping)`): keep scalars, summarize collections to size/keys, pass values through `scrub`; never dump verbatim. (data-model.md "Sanitized")
- [X] T006 Wire the sinks into both entrypoints: in `strava_mcp/mcp/server.py::run_server` and `strava_mcp/dashboard/server.py::run_dashboard`, call `setup_logging(settings.strava_log_path, level=settings.strava_log_level)` and `setup_audit(settings.strava_audit_path)`. (blocks every story; do not add the startup summary line yet — that is T017)
- [X] T007 [P] Unit test `tests/unit/test_config.py` (extend): assert defaults `strava_log_level == "INFO"` and `strava_audit_path == "./.logs/audit.log"`.
- [X] T008 [P] Unit test `tests/unit/test_audit.py` (new): `emit` writes exactly one line that `json.loads` parses with the four mandatory fields; `correlation_scope` sets/resets a stable 8-hex id and nested/concurrent scopes don't bleed; rotation produces valid standalone lines.

**Checkpoint**: `logging.py` + `audit.py` exist, are wired into `serve`/`dashboard`, and are unit-tested. Stories can begin.

---

## Phase 3: User Story 1 - Operator sees when something breaks (Priority: P1) 🎯 MVP

**Goal**: The human-readable log makes every common failure (Strava error, tool error, swallowed worker error, startup) and routine activity visible at the right severity, with a startup config summary and configurable level.

**Independent Test**: Force each failure class against offline fixtures and confirm a single, attributable log line at WARNING/ERROR (and INFO/DEBUG for routine), with no secrets — verified by the tests below without touching the audit trail.

### Tests for User Story 1 ⚠️ (write first, ensure they FAIL)

- [X] T009 [P] [US1] Contract test `tests/contract/test_strava_client_logging.py` (new): a non-2xx Strava response logs WARNING (4xx) / ERROR (5xx) with method, path, status, and fault message; a 200 logs INFO with latency; the bearer token never appears in caplog. (FR-001/002, SC-001)
- [X] T010 [P] [US1] Integration test `tests/integration/test_worker_error_logging.py` (new): a non-rate-limit failure inside `_run_with_cooldown` is logged with exception context (traceback/`exc_info`) and the worker still skips-and-continues. (FR-005, SC-001)
- [X] T011 [P] [US1] Test `tests/dashboard/test_dashboard_logging.py` (new): a dashboard request emits one INFO line with method, path, status, latency. (FR-004)
- [X] T011a [P] [US1] Tests for the two remaining SC-001 failure classes: (a) a tool that raises logs an ERROR human-log line naming the tool (extend `tests/contract/test_mcp_audit.py` or a new `tests/contract/test_mcp_tool_logging.py`); (b) `run_server` with a missing required scope logs the actionable startup error and exits non-zero (extend an existing serve test). (FR-003, SC-001)

### Implementation for User Story 1

- [X] T012 [P] [US1] Instrument `strava_mcp/client/http.py::StravaClient._request`: add a module logger; log the request at DEBUG, the response at INFO (`GET <path> -> <status> (<ms>ms)`), and WARNING (4xx) / ERROR (5xx + transport exception) with the parsed fault message — but an expected `429`/cooldown is logged at INFO/DEBUG, not WARNING; never log headers or the token. (FR-001/002)
- [X] T013 [US1] Add an `instrument(name)` wrapper in `strava_mcp/mcp/server.py` applied to each tool closure in `register_tools` (before `@mcp.tool`): time the call, log INFO on success / ERROR on exception, re-raise unchanged so tool return shapes and sentinels are untouched. (FR-003; audit emission added in US2 T019)
- [X] T014 [P] [US1] Raise dashboard request logging in `strava_mcp/dashboard/server.py` from DEBUG to INFO with method, path, status, latency, and client address (capture status + elapsed in `do_GET`/`_send`). (FR-004)
- [X] T015 [P] [US1] In `strava_mcp/sync/orchestrator.py::_run_with_cooldown`, replace `log.warning("%s failed: %s", label, exc)` with `log.exception("%s failed; skipping", label)` (preserve skip-and-continue behavior). (FR-005)
- [X] T016 [US1] Make the log level honor config: confirm `run_server`/`run_dashboard` pass `settings.strava_log_level` to `setup_logging` (from T006) and add a test-or-manual check that DEBUG surfaces per-request Strava lines. (FR-007, SC-007)
- [X] T017 [US1] Add a one-line startup config summary at INFO in `run_server` and `run_dashboard` (bind host/port, db path, log path, audit path, level); contains no secret. (FR-006)

**Checkpoint**: An operator reading only `./.logs/strava-mcp.log` can identify each failure class. US1 is independently testable.

---

## Phase 4: User Story 2 - Complete audit trail of every interaction (Priority: P1)

**Goal**: Every agent tool call, Strava call, and dashboard interaction produces structured JSONL audit events in `./.logs/audit.log`, correlated by `req_id`.

**Independent Test**: Drive one tool call, one dashboard load, and one worker enrichment (several Strava calls); confirm the audit file gains the expected request/response events per stream, each parseable with the four mandatory fields, with the enrichment's Strava calls sharing one `req_id` (tools issue no Strava call, so the `mcp` and `strava` streams are not cross-correlated).

> **Note**: US2 edits the same instrumentation points as US1 (`http.py`, `mcp/server.py`, `dashboard/server.py`), so run US2 **after** US1 rather than in parallel; each story stays independently testable through its own test files.

### Tests for User Story 2 ⚠️ (write first, ensure they FAIL)

- [X] T018 [P] [US2] Test `tests/contract/test_strava_audit.py` (new): a Strava call emits a `strava` request + response sharing one `req_id`, and the **multiple** Strava calls of a single enrichment all share one `req_id` (proving T021a); fields include method, path, query summary, status, latency, `rate_limit` snapshot; no token in any field. (FR-012, FR-008, SC-006, FR-015)
- [X] T019 [P] [US2] Test `tests/contract/test_mcp_audit.py` (new): a tool invocation emits `mcp` request + response events (tool, sanitized args, status, ms) that share one `req_id`; the call issues no Strava request (tools are pure readers), so no cross-stream correlation is asserted. (FR-011)
- [X] T020 [P] [US2] Test `tests/dashboard/test_dashboard_audit.py` (new): a page load emits exactly one `dashboard` interaction event (method, path, query, status, ms, client). (FR-013)

### Implementation for User Story 2

- [X] T021 [US2] In `strava_mcp/client/http.py::_request`, emit `strava` request + response audit events via `audit.emit` using `current_req_id()`, including method, path, sanitized query, status, latency, and `rate_limiter.snapshot()` when a limiter is attached. (FR-012)
- [X] T021a [US2] In `strava_mcp/sync/orchestrator.py`, open `correlation_scope()` around each worker logical unit — inside `_enrich_one` (so one activity's detail/laps/zones/streams/segment-effort GETs share one `req_id`) and around each `_run_with_cooldown` bootstrap unit — so the unit's `strava` audit events correlate. (FR-008, SC-006)
- [X] T022 [US2] In the `instrument` wrapper in `strava_mcp/mcp/server.py` (from T013), open `correlation_scope()` and emit `mcp` request (tool + `summarize_args`) and response (status ok/error, ms) audit events. (FR-011, FR-008)
- [X] T023 [US2] In `strava_mcp/dashboard/server.py::do_GET`, open `correlation_scope()` and emit one `dashboard` interaction event with method, path, sanitized query, response status, latency, and client address. (FR-013)

**Checkpoint**: All three audit streams populate `./.logs/audit.log`; a worker enrichment's Strava calls correlate via a shared `req_id`. US2 is independently testable.

---

## Phase 5: User Story 3 - Secrets & stability guarantees hold (Priority: P1)

**Goal**: No secret reaches either sink, and a logging/audit failure never breaks the observed operation; the mirror stays read-only / single-writer.

**Independent Test**: Inject token/secret-shaped values at every entry point and confirm redaction in both sinks; force the audit sink to fail and confirm the tool call / Strava call / dashboard request still completes.

### Tests for User Story 3 ⚠️ (write first, ensure they FAIL)

- [X] T024 [P] [US3] Extend `tests/unit/test_log_redaction.py`: a token/secret routed through an audit field is redacted in the serialized `audit.log` line (both sinks share redaction). (FR-015, SC-003)
- [X] T025 [P] [US3] Test `tests/unit/test_audit.py` (extend): with `setup_audit` pointed at an unwritable path, `emit` swallows the error and returns; a wrapped tool call / dashboard request still returns normally. (FR-016, SC-004)
- [X] T026 [P] [US3] Test `tests/dashboard/test_pure_reader_guard.py` (extend) or new assertion: enabling the audit trail does not cause any write to the mirror DB from the dashboard. (FR-017)

### Implementation for User Story 3

- [X] T027 [US3] Verify/finish: `RedactionFilter` is attached to the audit handler in `strava_mcp/audit.py` and `emit` wraps all exceptions; ensure the startup summary and every audit field pass through `scrub`/sanitizer; no secret in `_request` query summary. (FR-015/016)

**Checkpoint**: Redaction and best-effort guarantees proven; invariants intact.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T028 [P] Update `README.md` Logging/Dashboard section: human log vs `audit.log`, the three streams + fields, `STRAVA_LOG_LEVEL` / `STRAVA_AUDIT_PATH`, rotation.
- [X] T029 [P] Optional PATCH to `.specify/memory/constitution.md` *Logging* clause: path `./.database/strava-mcp.log` → current `./.logs/strava-mcp.log` + add `./.logs/audit.log`; bump 2.1.0 → 2.1.1 with a sync-impact note.
- [X] T030 Run `quickstart.md` scenarios 1–5, then `uv run pytest`, `uv run ruff check .`, `uv run mypy strava_mcp` — all green.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup (T001 for config). **BLOCKS all stories.**
- **US1 (Phase 3)**: after Foundational.
- **US2 (Phase 4)**: after Foundational; run **after US1** because it edits the same files (`http.py`, `mcp/server.py`, `dashboard/server.py`).
- **US3 (Phase 5)**: after Foundational; most guarantees are set in Phase 2, so US3 is largely verification — best run after US1+US2 are in place.
- **Polish (Phase 6)**: after all desired stories.

### Within Each User Story

- Tests written first and FAIL before implementation (Constitution II, regression-first).
- For US1: T012/T014/T015 are independent files; T013 and T017 both touch `mcp/server.py` → sequential.
- For US2: T021/T022/T023 are different files → parallelizable among themselves, but each builds on its US1 counterpart in the same file.

### Parallel Opportunities

- T001, T002 (Setup) in parallel.
- T004, T005, T007, T008 in Phase 2 in parallel (T003 and T006 are sequential dependencies for them where noted).
- Within US1: T009, T010, T011, T011a (tests) in parallel; T012, T014, T015 (impl, different files) in parallel.
- Within US2: T018, T019, T020 (tests) in parallel; T021a (worker `orchestrator.py`) is its own file, parallel-safe with T021/T022/T023.
- Within US3: T024, T025, T026 (tests) in parallel.

---

## Parallel Example: User Story 1 tests

```bash
Task: "Contract test for Strava client logging in tests/contract/test_strava_client_logging.py"
Task: "Integration test for worker swallowed-error logging in tests/integration/test_worker_error_logging.py"
Task: "Dashboard request logging test in tests/dashboard/test_dashboard_logging.py"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 Setup → 2. Phase 2 Foundational (CRITICAL) → 3. Phase 3 US1 → **STOP & VALIDATE**:
the operator can see failures in the human log. This alone delivers the "know when something breaks" half of the request.

### Incremental Delivery

1. Setup + Foundational → sinks live.
2. US1 → failure visibility (MVP, demo).
3. US2 → full audit trail (demo).
4. US3 → prove secrets/stability guarantees.
5. Polish → docs + constitution wording + full quickstart/lint/type/test gate.

---

## Notes

- [P] = different files, no incomplete-task dependency.
- US1 and US2 deliberately share instrumentation files; they remain independently *testable* via separate test modules even though they are not parallel-*editable*.
- No DB schema change; audit is file-only (mirror stays read-only / worker stays single writer).
- No new runtime dependency (stdlib `json`, `logging.handlers`, `contextvars`, `secrets`).
- Commit after each task or logical group.
