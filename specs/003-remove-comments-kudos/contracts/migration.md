# Contract: Upgrade Migration (drop comments/kudos)

A single guarded migration runs on DB open (from `engine.connect()` before `apply_schema()`).

## Trigger / guard

- **Runs** iff legacy structures are present: `comments` table OR `kudos` table exists, OR `activities` has a `kudos_count`/`comment_count` column.
- **No-op** on a freshly-created DB or one already migrated.

## Preconditions

- DB opened read/write by the single writer (worker). Readers use separate read-only connections.
- `PRAGMA foreign_keys` is ON in normal operation.

## Postconditions (all MUST hold)

1. Tables `comments` and `kudos` (and their indexes) do not exist.
2. `activities` has no `kudos_count`/`comment_count` columns; its three indexes exist; all other columns intact.
3. `activities` row count and every kept facet table's row count equal their pre-migration values.
4. Every activity that had `enriched_at NOT NULL` before still does (no visibility regression).
5. `raw_responses` is byte-for-byte unchanged (archive preserved, including legacy `comments`/`kudos` rows).
6. `PRAGMA foreign_key_check` reports no violations afterward.
7. Structure of the upgraded DB equals that of a fresh DB created by the new `schema.sql`.

## Invariants

- **Atomic**: rebuild happens in one transaction; interruption rolls back to the pre-migration state.
- **Idempotent**: safe to run on every open; second run is a no-op.
- **Non-destructive** beyond the explicitly removed comments/kudos served structures.

## Tests (new: `tests/integration/test_migration_drop_comments_kudos.py`)

- Seed a DB using the **old** schema with activities, comments, kudos rows, and non-null `kudos_count`/`comment_count`; run `connect()`; assert all postconditions 1–7.
- Idempotency: run `connect()` twice; second run changes nothing and does not error.
- Preservation: a kept facet (e.g. laps) and `raw_responses` rows survive unchanged.
- Fresh DB: `connect()` on a new path creates the new schema and the migration is a no-op.
