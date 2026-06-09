# Phase 0 Research: Remove Comments & Kudos

All Technical Context unknowns were resolved against the codebase (SQLite 3.46.1 dev; `PRAGMA foreign_keys=ON`; schema applied idempotently via `engine.connect()` → `apply_schema()`).

## R1 — How to physically remove the two columns from `activities`

**Decision**: Use the canonical SQLite **table-rebuild** ("12-step") pattern for `activities`: create `activities_new` with the new column set, `INSERT … SELECT` the kept columns, drop the old table, `RENAME` the new one, then recreate the three indexes (`idx_activities_start_epoch`, `idx_activities_sport_type`, `idx_activities_enriched_at`). Wrap the whole thing in a single transaction.

**Rationale**: Version-independent — works on any SQLite, unlike `ALTER TABLE … DROP COLUMN` which requires ≥ 3.35.0 and the platform's bundled libsqlite3 is not guaranteed. Atomic: a crash mid-rebuild rolls back to the pre-migration state (satisfies the "interrupted rebuild" edge case and FR-015). Preserves all kept data and `id` values (children keep referencing the same ids).

**Alternatives considered**: `ALTER TABLE activities DROP COLUMN kudos_count` (×2) — simplest, and the columns are unindexed so it would succeed on 3.46.1, but rejected as the *sole* mechanism for portability/atomicity reasons. Logical hide (keep columns, stop reading) — rejected by clarification Option A.

## R2 — Foreign keys during the rebuild

**Decision**: Toggle `PRAGMA foreign_keys=OFF` **before** `BEGIN`, perform the rebuild + `RENAME`, `COMMIT`, then `PRAGMA foreign_keys=ON` and run `PRAGMA foreign_key_check`. (`foreign_keys` is a no-op if changed inside a transaction, so it must be set outside.)

**Rationale**: `laps`, `activity_streams`, `activity_zones`, `segment_efforts` (and the soon-to-be-dropped `comments`/`kudos`) declare `REFERENCES activities(id)`. Dropping/renaming the parent with FK enforcement on can fail or rewrite child rows; disabling enforcement for the duration and re-validating afterward is the documented-safe sequence. Order: **drop `comments` and `kudos` first** (removes their FK references to `activities`), then rebuild `activities`.

**Alternatives considered**: `PRAGMA legacy_alter_table` — narrower, older mechanism; the explicit FK-off + `foreign_key_check` is clearer and self-validating.

## R3 — Where the migration runs and how it stays idempotent

**Decision**: Add `strava_mcp/db/migrations.py` with a single entry point invoked from `engine.connect()` **before** `apply_schema()`. Guard by schema introspection: run only if `comments`/`kudos` tables exist **or** `activities` still has a `kudos_count`/`comment_count` column (via `PRAGMA table_info`). On a fresh or already-migrated DB the guard is false → no-op. Then `apply_schema()` (now without the legacy DDL) runs as today.

**Rationale**: No migration framework or `schema_version` exists; introspection is the lightest reliable guard and is naturally idempotent. Running pre-`apply_schema` means the new `schema.sql` never re-creates the dropped objects. Matches the "re-run on already-migrated database is a no-op" edge case.

**Alternatives considered**: Add a `schema_version`/`user_version` PRAGMA and gate on it — more machinery than a one-shot removal needs; introspection guard is sufficient and self-correcting. (Noted as a possible future convention but YAGNI here.)

## R4 — Stop fetching, keep dual-write integrity for the rest

**Decision**: In `sync/resources/activities.py::enrich()` delete the two `_safe_list("/…/comments")` and `_safe_list("/…/kudos")` calls; change `repo.enrich(...)` to no longer pass `comments`/`kudos`. In `db/repositories/activities.py::enrich()` drop those params and the `_write_comments`/`_write_kudos` calls; delete those write methods and the `comments()`/`kudos()` read methods; remove `kudos_count`/`comment_count` from `_PROMOTED_KEYS` and `_summary_view()`. Visibility still stamps `enriched_at` **last, only after streams** — unchanged.

**Rationale**: The enrichment unit becomes `detail + laps + zones + streams`. Dual-write remains intact for every facet still fetched (Principle I). The streams visibility invariant (Principle III/IV, R8) is untouched, so no activity regresses (FR-004/SC-005).

**Alternatives considered**: Keep params but pass `[]` — leaves dead code/vocabulary behind, violating "complete removal" and vocabulary discipline. Rejected.

## R5 — `raw_responses` and `detail_json` handling

**Decision**: Preserve all existing `raw_responses` rows with `resource_type IN ('comments','kudos')` and all `detail_json` blobs untouched; simply stop writing new comments/kudos raw rows (the write methods are deleted). Do **not** scrub these blobs.

**Rationale**: Session 2026-06-09 clarification (Option B): the append-only archive is the immutable durable backup, never served to agents or the dashboard, so it stays. Avoids destructive rewrites of an append-only store (Principle I). No reader path exposes these rows.

**Alternatives considered**: Total scrub of raw archive + `detail_json` (clarification Option A) — rejected by the user.

## R6 — Removing the two MCP tools safely

**Decision**: Delete `get_comments`/`get_kudos` from `mcp/tools/activities.py` and their `@mcp.tool` registrations in `mcp/server.py`. The shared `_facet` helper and the other facet tools (`get_laps`, `get_activity_zones`) remain. A client calling the now-absent tool gets FastMCP's standard "unknown tool" error.

**Rationale**: Satisfies FR-006/FR-014 (capability gone; unknown-operation error, never fabricated/empty-as-real data). Pure-reader boundary (Principle I) preserved for remaining tools.

**Alternatives considered**: Keep tools returning an empty list — rejected: that exposes a capability with no data behind it (misleading; violates "no fabricated/partial results", Principle III).

## R7 — Constitution & vocabulary amendment

**Decision**: Amend `.specify/memory/constitution.md` Principle III: redefine "fully enriched" as `detail + laps + zones + streams` and relax the "stable schemas" clause to allow this governed tool removal. Bump version **1.0.0 → 2.0.0** (MAJOR: a principle is redefined) with a SYNC IMPACT REPORT note. Purge comments/kudos from CONTEXT.md vocabulary and the human docs (README, PRD, PLAN, specs/001) in the same change.

**Rationale**: The constitution states it wins over convenience, and its Governance section permits amendment with rationale + version bump + dependent-template updates. Vocabulary discipline (Principle I) requires the synonyms not to linger in new code/docs.

**Alternatives considered**: MINOR bump — rejected; redefining a principle's concrete rule and removing "stable" tools is backward-incompatible governance → MAJOR per the versioning policy.
