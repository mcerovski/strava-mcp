# Implementation Plan: Remove Comments & Kudos for Faster Sync

**Branch**: `003-remove-comments-kudos` | **Date**: 2026-06-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-remove-comments-kudos/spec.md`

## Summary

Remove the per-activity **comments** and **kudos** facets from the entire product to cut two Strava read requests per activity (6 → 4), so backfill/poll cover ~50% more activities per day on the same budget. Removal spans: the two enrichment fetches, the `comments`/`kudos` normalized tables, the `kudos_count`/`comment_count` promoted columns, the `get_comments`/`get_kudos` MCP tools, and all documentation/vocabulary. Existing deployments upgrade in place via a guarded, idempotent, atomic migration that drops the two tables and rebuilds `activities` without the two columns, leaving an upgraded database structurally identical to a fresh one. The append-only `raw_responses` archive and `detail_json` blobs are preserved (per Session 2026-06-09 clarification). Visibility ("fully synced") is redefined to depend only on `detail + laps + zones + streams`, so no previously-visible activity regresses.

## Technical Context

**Language/Version**: Python 3.11+ (managed by `uv`)

**Primary Dependencies**: FastMCP (`streamable-http`), `httpx` (sync, worker thread), stdlib `sqlite3`

**Storage**: SQLite (WAL mode, single writer, concurrent readers); local file under `./.database/`. Dev SQLite is 3.46.1; migration uses a version-independent table-rebuild so it does not depend on `ALTER TABLE … DROP COLUMN` (3.35+).

**Testing**: `pytest` via `uv run`; DB-layer tests use a real temp SQLite file (WAL); Strava interactions use recorded fixtures (no live API).

**Target Platform**: Local single-user service bound to `127.0.0.1` (loopback only).

**Project Type**: Single project — background sync worker + MCP read server + local dashboard, sharing one SQLite mirror.

**Performance Goals**: Per-activity read cost 6 → 4 requests (−33%); ≥ ~45% more activities fully synced per day for a fixed read budget; deterministic rate-limit cooldown unchanged.

**Constraints**: Read-only OAuth scopes only; no live Strava calls in tests; dual-write integrity preserved for remaining facets; migration must be atomic (crash-safe) and idempotent; no manual DB steps on upgrade; preserve `raw_responses`/`detail_json`.

**Scale/Scope**: Single athlete's history (hundreds–low thousands of activities). Code touch: ~2 source modules of logic + schema + a new migration + tool/registration removal + docs + tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| **I. Code Quality & Architectural Integrity** | Module separation preserved; tools remain pure DB readers; dual-write kept for remaining facets; **lean columns** improved (two promoted columns removed); typed boundaries via `repositories/`; **vocabulary discipline** requires purging "comments"/"kudos" from CONTEXT.md and code. | ✅ PASS (vocabulary updates are in-scope) |
| **II. Testing Standards (NON-NEGOTIABLE)** | New behaviors get tests: migration (drop tables, rebuild columns, data preserved, idempotent, atomic), redefined visibility invariant (no comments/kudos), reduced enrichment request count, dual-write for remaining facets. Regression-first; real SQLite; offline fixtures. | ✅ PASS |
| **III. User Experience Consistency** | Two rules **conflict** with this feature: (a) "An activity is visible only when fully enriched (detail + laps + **comments + kudos** + zones + streams)"; (b) "**Stable schemas** … tool return shapes are documented and stable" — we remove `get_comments`/`get_kudos`. | ⚠️ INTENTIONAL DEVIATION — requires a governed **constitution amendment** (see Complexity Tracking). Otherwise compliant: tools still return stored data or honest signals; no partial data exposed. |
| **IV. Performance & Rate-Limit Discipline** | Deterministic cooldown, checkpoint/resume, single-writer/WAL, indexed reads all unchanged; per-activity request count drops. Net-positive for the rate budget. | ✅ PASS |
| **Tech & Security Constraints** | Python/`uv`, FastMCP loopback, read-only scopes, secrets in `.database/` — all unchanged; fewer endpoints called. | ✅ PASS |

**Gate result**: PASS with one documented deviation (Principle III amendment), which the constitution's own Governance section explicitly permits via amendment + version bump. Recorded in Complexity Tracking; executed as a planned task.

## Project Structure

### Documentation (this feature)

```text
specs/003-remove-comments-kudos/
├── plan.md              # This file
├── research.md          # Phase 0 output — migration strategy & decisions
├── data-model.md        # Phase 1 output — schema before/after + migration steps
├── quickstart.md        # Phase 1 output — how to validate the change
├── contracts/
│   ├── mcp-tools.md      # Tool-surface delta (get_comments/get_kudos removed)
│   └── migration.md      # Migration contract (pre/postconditions, idempotency)
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit-specify)
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

```text
strava_mcp/
├── db/
│   ├── engine.py                    # connect()/apply_schema() — ADD: guarded migration hook
│   ├── schema.sql                   # REMOVE: comments/kudos tables + count columns
│   ├── migrations.py                # NEW: idempotent, atomic drop+rebuild migration
│   └── repositories/
│       └── activities.py            # REMOVE: comments/kudos params, _write_*/read methods,
│                                    #         kudos_count/comment_count from _PROMOTED_KEYS & _summary_view
├── sync/resources/activities.py     # REMOVE: comments/kudos _safe_list fetches in enrich()
├── mcp/
│   ├── tools/activities.py          # REMOVE: get_comments/get_kudos functions
│   └── server.py                    # REMOVE: get_comments/get_kudos @mcp.tool registrations
└── dashboard/                       # VERIFY: no comments/kudos usage (none found)

tests/
├── contract/test_enrichment_tools.py, test_multi_client.py   # UPDATE: drop tool assertions
├── integration/test_enrichment.py, test_enrichment_streams_invariant.py,
│   test_dual_write.py, test_backfill.py, test_quickstart.py   # UPDATE: signatures/fixtures/loops
├── integration/test_migration_drop_comments_kudos.py          # NEW: upgrade migration tests
└── conftest.py                                                 # UPDATE: fixture handler docstring

# Docs / governance to amend (vocabulary discipline):
.specify/memory/constitution.md      # AMEND Principle III + version bump
CONTEXT.md · README.md · PRD.md · PLAN.md · specs/001-*/spec.md · specs/001-*/data-model.md
```

**Structure Decision**: Single-project brownfield modification. No new modules beyond `strava_mcp/db/migrations.py`; everything else is surgical removal within the existing `config/auth/client/db/sync/mcp/dashboard` boundaries, preserving module separation (Principle I).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| **Constitution amendment to Principle III** (redefine "fully enriched" to exclude comments/kudos; remove two "stable" tools) | The feature's explicit goal is complete removal of comments/kudos; the current principle hard-codes them into the enrichment definition and declares the tool surface stable. Governance permits amendment with rationale + version bump. | Keeping the principle as-is would make every removal task a constitution violation. "Just ignore the conflict" rejected: the constitution states it wins over convenience, so it must be amended, not bypassed. Versioned **MAJOR 1.0.0 → 2.0.0** (a principle is redefined). |
| **New `migrations.py` (table-rebuild migration)** | Existing DBs physically contain the tables/columns; FR-011/FR-015 require physical removal that is atomic + idempotent, and there is no migration framework. | `ALTER TABLE … DROP COLUMN` rejected as the sole mechanism: depends on SQLite ≥ 3.35 (platform-variable bundled libsqlite3) and is non-portable; the 12-step table-rebuild is version-independent and atomic in one transaction. Doing nothing (logical hide) rejected by the Session 2026-06-09 clarification (Option A: full physical removal). |
