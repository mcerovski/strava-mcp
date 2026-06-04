# Implementation Plan: Strava MCP Local Mirror

**Branch**: `001-strava-mcp-mirror` | **Date**: 2026-06-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-strava-mcp-mirror/spec.md`

## Summary

A single locally-run Python process that (1) authorizes once to Strava with full read
scopes, (2) runs a server-owned background worker that **backfills** the athlete's entire
history newest→oldest with full per-activity **enrichment including streams**, then **polls**
every 12h for new activities (insert-only, 14-day lookback, dedupe-by-id), and (3) serves
that data to AI agents over a loopback FastMCP HTTP server whose tools are **pure SQLite
reads** that never call Strava. Storage is dual-write: verbatim JSON into an append-only
`raw_responses` store plus lean normalized tables (promoted indexed columns + `detail_json`).
The technical approach is fixed by the PRD, CONTEXT glossary, and three ratified ADRs; this
plan translates them into a concrete module layout, data model, tool contracts, and a
slice-ordered build per PLAN.md.

## Technical Context

**Language/Version**: Python 3.11+ (managed exclusively by `uv`).

**Primary Dependencies**:
- `fastmcp` — MCP server, `streamable-http` transport bound to loopback.
- `httpx` — Strava HTTP client (bearer auth, token refresh, rate-limit header parsing).
- Standard library `sqlite3` (WAL mode) — no ORM; thin typed repository layer.
- Standard library `http.server` / `webbrowser` — OAuth local callback + browser open.
- `pydantic` (or stdlib `dataclasses`) — config loading and typed boundaries (see research).
- Dev: `pytest`, `ruff` (lint + format), a type checker (`mypy`/`pyright` — see research).

**Storage**: Local SQLite database at `./.database/strava.db` (WAL mode, single writer).
Append-only `raw_responses` table + lean normalized tables. No external datastore.

**Testing**: `pytest` against a real temp SQLite DB (WAL); Strava interactions tested with
recorded fixtures derived from `strava-api-spec/` — **never the live API**.

**Target Platform**: Local single-user host (Linux/macOS/Windows); loopback-only service.

**Project Type**: Single Python project — long-running CLI service (`auth` + `serve`).

**Performance Goals**:
- Agent reads served from indexed promoted columns; list/filter queries return well under
  1s for a multi-year history; aggregates computed in SQL, not Python.
- Worker is a good Strava citizen: stays within the Read budget (100/15min, 1000/day),
  cooling down deterministically to the next reset rather than 429-looping.

**Constraints**:
- MCP tools MUST NOT call Strava (only the worker does) — architectural invariant.
- Loopback bind only (`127.0.0.1`); no network auth layer.
- Read-only OAuth scopes only; insert-only persistence (no edit/delete reconciliation).
- Secrets never leave `./.database/`; never logged.
- Backfill must be checkpointed/resumable with zero re-fetch on restart.

**Scale/Scope**: One athlete; history up to ~10k+ activities over many years. Streams are
the dominant data volume (stored per-type as JSON arrays + metadata, not per-sample rows).
Backfill of a multi-year history legitimately spans hours/days bounded by rate limits.

*No NEEDS CLARIFICATION remain* — the PRD, CONTEXT glossary, and ADRs 0001–0003 fix every
material decision. Open library micro-choices (config lib, type checker) are resolved in
`research.md` with documented defaults.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Derived from `.specify/memory/constitution.md` v1.0.0. Each gate maps to a principle.

### I. Code Quality & Architectural Integrity
- [x] **Module separation** preserved: `config`, `auth`, `client`, `db`, `sync`, `mcp`
      evolve independently (see Project Structure).
- [x] **Tools are pure readers**: `mcp/tools/` never import the Strava client; only
      `sync/` calls Strava. (Enforced by structure + a test asserting no client import.)
- [x] **Dual-write mandatory**: every resource fetched writes both `raw_responses` and its
      normalized table (data-model.md encodes this; repositories expose paired writes).
- [x] **Lean columns + `detail_json`**: promoted columns justified per query need in
      data-model.md; everything else in `detail_json`.
- [x] **Typed boundaries**: DB access via `db/repositories/`; type hints on public funcs;
      `ruff` + type check clean.
- [x] **Vocabulary discipline**: code/log/tool text uses CONTEXT.md terms (backfill,
      frontier, poll, enrichment, fully synced, raw store); avoided synonyms banned.

### II. Testing Standards (NON-NEGOTIABLE)
- [x] **Acceptance-criteria coverage**: every slice's acceptance checkbox maps to ≥1 test
      (tasks.md will enumerate; quickstart.md lists the validation scenarios).
- [x] **No live Strava calls in tests**: fixtures from `strava-api-spec/`; offline + deterministic.
- [x] **Critical behaviors tested explicitly**: insert-only + dedupe-by-id; deterministic
      cooldown to next window; checkpoint/resume (no re-fetch); fully-synced flips only after
      streams; "not yet synced" sentinel.
- [x] **DB tests use real temp SQLite (WAL)**, not mocks.
- [x] **Regression-first on bugs**: enforced by review gate (process, not code).

### III. User Experience Consistency
- [x] **Uniform tool semantics**: `get_*` (one) / `list_*` (collection); return stored data
      or documented `not yet synced` — never partial/fabricated (contracts/ encodes this).
- [x] **Partial data never exposed**: activity visible only when fully enriched (single-unit
      write + visibility flag, see data-model.md).
- [x] **Observability**: `sync_status` reports frontier date, % complete, fully-synced flag,
      counts, rate-limit budget, cooldown ETA.
- [x] **Actionable failures**: `serve` exits with `run uv run strava-mcp auth` on scope gap.
- [x] **Stable schemas**: new Strava fields surface via `detail_json` without breaking contracts.

### IV. Performance & Rate-Limit Discipline
- [x] **Deterministic rate budget**: read `X-ReadRateLimit-Usage`/`X-RateLimit-Usage`; on
      exhaustion/429 cool down to known next reset (quarter-hour / midnight UTC).
- [x] **Resumable/checkpointed**: backfill checkpoints after every page; restart resumes from frontier.
- [x] **Single writer, concurrent readers**: WAL; only the worker writes; reads never block.
- [x] **Cheap queries**: filters hit indexed promoted columns; aggregates in SQL.
- [x] **Streams stored efficiently**: per type as JSON + metadata, not per-sample rows.

### Technology & Security Constraints
- [x] Python 3.11+ via `uv`; deps in `pyproject.toml` + `uv.lock`.
- [x] FastMCP `streamable-http` bound to `127.0.0.1`; no network auth layer.
- [x] Read-only scopes only; no write scopes requested/used.
- [x] Tokens persist in DB; `.gitignore` excludes `.database/`, `.env`, `.venv/`; no secret outside `.database/`.
- [x] Logs to stdout + rotating `./.database/strava-mcp.log`; no secrets in logs.

**Result: PASS** (initial). No violations → Complexity Tracking left empty.

**Post-design re-check (after Phase 1): PASS.** The design artifacts uphold every gate and
add no new complexity:
- `data-model.md` encodes dual-write (`raw_responses` + normalized), lean promoted columns +
  `detail_json`, the `enriched_at` visibility flag (no partial activities), per-type stream
  JSON, and single-row `sync_state` for deterministic cooldown/resume.
- `contracts/mcp-tools.md` fixes `get_*`/`list_*` semantics and the `not yet synced` sentinel,
  and lists a pure-reader guard test (tools import neither `client` nor `sync`).
- `contracts/cli.md` fixes scope-check-or-exit, loopback bind, single-writer worker, and
  no-secrets logging.
- No design element required a constitution exception → Complexity Tracking remains empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-strava-mcp-mirror/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── mcp-tools.md     #   MCP read-tool contracts (inputs/outputs/errors)
│   └── cli.md           #   `auth` / `serve` CLI command contracts
├── checklists/
│   └── requirements.md  # Spec quality checklist (/speckit-specify output)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created here)
```

### Source Code (repository root)

Single Python project. Layout matches PRD §4 (strict module separation); tests mirror the
package and are split by kind.

```text
pyproject.toml           # uv project: deps, entrypoint `strava-mcp`
uv.lock
strava_mcp/
├── __init__.py
├── __main__.py          # CLI entrypoints: `auth`, `serve` (sync runs inside serve)
├── config.py            # Settings from env/.env: client creds, paths, port, scopes, sync window
├── logging.py           # Dual sink (stdout + rotating ./.database/strava-mcp.log) + secret redaction
├── auth/
│   ├── __init__.py
│   ├── oauth.py         # Authorization-code flow + local callback server on 127.0.0.1
│   └── tokens.py        # Token storage (DB) + auto-refresh when expires_at is near
├── client/
│   ├── __init__.py
│   ├── http.py          # Thin Strava client: base URL, bearer auth, JSON, refresh hook
│   └── ratelimit.py     # Parse X-RateLimit/X-ReadRateLimit; deterministic cooldown; 429 backoff
├── db/
│   ├── __init__.py
│   ├── schema.sql       # DDL: raw_responses + normalized tables + indexes
│   ├── engine.py        # Connection, WAL pragma, migration/bootstrap
│   └── repositories/    # Typed read/write helpers per resource (paired raw+normalized writes)
│       ├── __init__.py
│       ├── athlete.py
│       ├── activities.py
│       ├── streams.py
│       ├── gear.py
│       ├── routes.py
│       └── segments.py    # (sync_state access lives in sync/state.py, not a repository)
├── sync/
│   ├── __init__.py
│   ├── orchestrator.py  # Worker state machine: BOOTSTRAP→BACKFILL→POLL; checkpoints
│   ├── state.py         # sync_state access: frontier, newest-synced, run log, rl snapshots
│   └── resources/       # One syncer per resource
│       ├── __init__.py
│       ├── athlete.py
│       ├── activities.py # summaries + enrichment (detail/laps/comments/kudos/zones/streams/efforts)
│       ├── gear.py
│       ├── routes.py
│       └── segments.py
└── mcp/
    ├── __init__.py
    ├── server.py        # FastMCP app, HTTP transport, tool registration, owns worker thread
    └── tools/           # MCP tools — pure DB reads, never call Strava
        ├── __init__.py
        ├── athlete.py
        ├── activities.py
        ├── streams.py
        ├── gear.py
        ├── routes.py
        ├── segments.py
        ├── sync.py      # sync_status, sync_now
        └── summaries.py # summarize_training

tests/
├── conftest.py          # temp SQLite (WAL) fixture; recorded Strava fixtures loader
├── fixtures/            # recorded API JSON derived from strava-api-spec/
├── contract/            # MCP tool + CLI contract tests (shapes, not-yet-synced sentinel)
├── integration/         # backfill/poll/enrichment flows against fixtures + real temp DB
└── unit/                # ratelimit math, token refresh, config, json promotion
```

**Structure Decision**: Single project, six top-level packages mirroring the PRD's strict
module boundaries (`config`, `auth`, `client`, `db`, `sync`, `mcp`). The boundary that matters
most — tools never touch Strava — is structural (`mcp/tools/` depends only on `db/`) and
guarded by a test asserting no `client`/`sync` import from `mcp/tools/`. Tests mirror the
package and separate contract / integration / unit so each PLAN slice's acceptance criteria
map onto concrete test files.

## Complexity Tracking

> No constitution violations. No entries required.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| _(none)_ | — | — |
