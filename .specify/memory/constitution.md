<!--
SYNC IMPACT REPORT
==================
Version change: (template, unversioned) → 1.0.0
Bump rationale: First concrete ratification of the constitution from the template.
  MAJOR (1.0.0) because this establishes the initial governing principle set.

Modified principles:
  [PRINCIPLE_1_NAME] → I. Code Quality & Architectural Integrity
  [PRINCIPLE_2_NAME] → II. Testing Standards (NON-NEGOTIABLE)
  [PRINCIPLE_3_NAME] → III. User Experience Consistency
  [PRINCIPLE_4_NAME] → IV. Performance & Rate-Limit Discipline
  [PRINCIPLE_5_NAME] → (removed; user requested four focused principles)

Added sections:
  - Technology & Security Constraints (was [SECTION_2_NAME])
  - Development Workflow & Quality Gates (was [SECTION_3_NAME])

Removed sections:
  - Fifth core principle slot (consolidated; project scoped to four principles)

Templates requiring updates:
  ✅ .specify/templates/plan-template.md — Constitution Check gates align (verified)
  ✅ .specify/templates/spec-template.md — no mandatory-section conflicts (verified)
  ✅ .specify/templates/tasks-template.md — testing/perf task categories align (verified)
  ✅ .specify/templates/checklist-template.md — generic; no changes needed (verified)

Follow-up TODOs:
  - None. Ratification date set to first adoption (2026-06-04).
-->

# strava-mcp Constitution

## Core Principles

### I. Code Quality & Architectural Integrity

The codebase MUST preserve the strict module separation defined in the PRD: `config`,
`auth`, `client`, `db`, `sync`, and `mcp` evolve independently. MCP tools MUST be pure
database readers and MUST NOT call the Strava API directly; only the background sync
worker calls Strava. This boundary is non-negotiable — a tool that issues a network
call is a defect, not a feature.

Rules:
- **Dual-write is mandatory.** Every resource fetched from Strava MUST be written both
  verbatim into `raw_responses` (append-only) and into its normalized table. Code that
  writes one without the other is incomplete.
- **Lean columns + `detail_json`.** Normalized tables promote only fields agents filter,
  sort, or aggregate on; everything else stays in `detail_json`. Adding a promoted column
  MUST be justified by an actual query need, not anticipation.
- **Typed boundaries.** DB access goes through the `repositories/` layer; modules do not
  reach across boundaries with ad-hoc SQL. Public functions carry type hints and the code
  passes static checks (e.g. `ruff`/type checking) cleanly before merge.
- **Vocabulary discipline.** Code, comments, log messages, and tool descriptions MUST use
  the terms fixed in CONTEXT.md (backfill, frontier, poll, enrichment, fully synced, raw
  store). The avoided synonyms (import, refresh, cache, etc.) MUST NOT appear in new code.

Rationale: This is a long-running local service where sync and serving must evolve
without coupling. The raw store is the durable backup; the normalized tables are a
rebuildable projection. Confusing the two, or letting a reader touch the network, breaks
the core guarantee that "the database is the source of truth for the agent."

### II. Testing Standards (NON-NEGOTIABLE)

Every vertical slice in PLAN.md ships with automated tests that prove its acceptance
criteria. A slice is not "done" until its acceptance checklist is covered by tests that
run green in CI/local `uv run`.

Rules:
- **Acceptance-criteria coverage.** Each checkbox in a slice's acceptance criteria MUST map
  to at least one test. Untested acceptance criteria block the slice.
- **No live Strava calls in tests.** Strava interactions MUST be tested against recorded
  fixtures / the OpenAPI spec, never the live API. Tests run offline and deterministically.
- **Critical behaviors require explicit tests:** insert-only + dedupe-by-id (back-dated
  upload caught, existing rows never mutated), rate-limit cooldown to the deterministic next
  window, checkpoint/resume after restart (no re-fetch), "fully synced" flips only after
  streams are present, and the "not yet synced" sentinel for unreached activities.
- **DB-layer tests use a real SQLite database** (temp file in WAL mode), not mocks, so
  schema, indexes, and `json_extract` paths are exercised as in production.
- **Regression-first on bugs.** A bug fix MUST add a failing test that reproduces it before
  the fix lands.

Rationale: The sync state machine has many edge conditions (rate limits, resumption,
back-dating) that are expensive to verify by hand and easy to silently break. Fixtures keep
tests fast, deterministic, and within Strava's rate budget.

### III. User Experience Consistency

The "user" is an AI agent consuming the MCP tool surface. That surface MUST be predictable,
self-describing, and uniform across every tool.

Rules:
- **Uniform tool semantics.** Read tools return stored data or the documented `not yet
  synced` signal — never a partial or fabricated result. Naming follows the established
  pattern (`get_*` for one resource, `list_*` for collections).
- **Partial data is never exposed.** An activity is visible only when fully enriched
  (detail + laps + comments + kudos + zones + streams). Tools MUST NOT return half-enriched
  activities.
- **Observability is part of UX.** `sync_status` MUST accurately report frontier date,
  % complete, fully-synced flag, counts, current rate-limit budget, and cooldown ETA, so an
  agent can reason about what is and isn't available yet.
- **Actionable failure modes.** Operator-facing errors (e.g. insufficient OAuth scope on
  `serve`) MUST exit with concrete instructions (`run uv run strava-mcp auth`) rather than a
  stack trace or silent failure.
- **Stable schemas.** Tool return shapes are documented and stable; new Strava fields surface
  through `detail_json` without breaking existing tool contracts.

Rationale: Agents cannot ask clarifying questions mid-call. Consistency, honest "not yet
synced" signaling, and trustworthy status reporting are what make the server safe to query
during an in-progress backfill.

### IV. Performance & Rate-Limit Discipline

The server MUST be a good Strava citizen and a cheap local query target simultaneously.

Rules:
- **Respect the rate budget deterministically.** The client MUST read
  `X-ReadRateLimit-Usage` / `X-RateLimit-Usage` after each response and, on exhaustion or
  `429`, COOLDOWN by sleeping until the *known* next reset (quarter-hour / midnight UTC) —
  never a blind retry loop or fixed sleep guess.
- **Resumable, checkpointed work.** Backfill checkpoints after every page; a restart resumes
  from the frontier with zero re-fetching of already-stored activities.
- **Single writer, concurrent readers.** SQLite runs in WAL mode; only the worker writes.
  Read tools MUST NOT take write locks or block on the worker.
- **Queries are cheap.** Tool filters (date range, sport_type, segment_id) MUST hit indexed
  promoted columns; aggregates (`summarize_training`) MUST be computed in SQL, not by loading
  rows into Python. Unindexed `json_extract` scans are acceptable only for rare, non-hot paths.
- **Streams are the bulk; store them efficiently.** Stream data is persisted per type as JSON
  with metadata, not exploded into per-sample rows.

Rationale: Strava's 15-minute and daily windows make naive fetching fail within minutes; the
mirror exists precisely so agent queries are fast and free of API cost. Both ends of that
trade — disciplined fetching and indexed reads — are load-bearing.

## Technology & Security Constraints

- **Runtime & tooling.** Python 3.11+, managed exclusively by `uv`. Dependencies live in
  `pyproject.toml` and are locked in `uv.lock`. Entrypoints run via `uv run strava-mcp
  <auth|serve>`.
- **Transport.** FastMCP `streamable-http`, bound to `127.0.0.1` only. No network auth layer
  is added (single-user loopback); the loopback bind is therefore mandatory, not optional.
- **Scope.** Read-only OAuth scopes only (`read`, `read_all`, `profile:read_all`,
  `activity:read`, `activity:read_all`). No write scopes may be requested or used.
- **Secrets.** Tokens persist in the DB after first auth; `.env` only seeds the initial run.
  `.gitignore` MUST continue to exclude `.database/`, `.env`, and `.venv/`. No secret may be
  written outside `.database/` or committed to git.
- **Logging.** Progress logs go to stdout and the rotating file `./.database/strava-mcp.log`
  (gitignored). Logs MUST NOT contain tokens or secrets.

## Development Workflow & Quality Gates

- **Slice-based delivery.** Work follows the vertical slices in PLAN.md, honoring the
  dependency shape `1 → 2 → 3 → { 4 → { 5, 6 }, 7, 8 }`. Each slice is independently demoable.
- **Definition of done (per slice):** acceptance criteria covered by passing tests; static
  checks/linting clean; vocabulary (CONTEXT.md) respected; no live-API calls in tools or
  tests; logging present where the slice specifies it.
- **Review gate.** Every change is reviewed against these principles. A reviewer MUST reject
  changes that: let a tool call Strava, expose partial/un-enriched data, skip the dual-write,
  introduce a non-deterministic rate-limit wait, or land behavior without tests.
- **Complexity is justified or removed.** Added abstraction, tables, or promoted columns MUST
  cite the concrete need they serve; speculative generality is rejected (YAGNI).

## Governance

This constitution supersedes ad-hoc practice for the strava-mcp project. When guidance here
conflicts with convenience, this document wins.

- **Amendments** are made by editing this file with a clear rationale, bumping the version per
  the policy below, and updating any dependent templates in `.specify/templates/` in the same
  change.
- **Versioning policy (semantic):**
  - **MAJOR** — backward-incompatible governance change: a principle removed or redefined.
  - **MINOR** — a new principle or section added, or materially expanded guidance.
  - **PATCH** — clarifications, wording, or typo fixes with no semantic change.
- **Compliance review.** PRs and reviews MUST verify compliance with the Core Principles. The
  per-slice Definition of Done is the routine enforcement point; the review gate is the
  backstop.
- **Runtime guidance.** Day-to-day development context lives in PRD.md, CONTEXT.md (canonical
  vocabulary), and PLAN.md; agent-specific operating notes live in CLAUDE.md. These elaborate
  but never override the principles above.

**Version**: 1.0.0 | **Ratified**: 2026-06-04 | **Last Amended**: 2026-06-04
