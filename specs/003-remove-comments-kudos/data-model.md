# Phase 1 Data Model: Remove Comments & Kudos

## Entities affected

| Entity | Change |
|--------|--------|
| **activities** | Drop promoted columns `kudos_count`, `comment_count`. All other columns, indexes, and `id` values unchanged. Visibility gate `enriched_at` semantics unchanged (set last, after streams). |
| **comments** (table) | **Dropped** entirely (table + `idx_comments_activity`). |
| **kudos** (table) | **Dropped** entirely (table + `idx_kudos_activity`). |
| **raw_responses** | **Unchanged.** Existing rows with `resource_type IN ('comments','kudos')` are preserved (append-only durable backup). No new comments/kudos rows are written. |
| **activity_streams / laps / activity_zones / segment_efforts / segments / gear / routes / athlete / tokens / sync_state** | **Unchanged.** |

## `activities` — before → after

```diff
 CREATE TABLE activities (
   id                    INTEGER PRIMARY KEY,
   ... (start_date … average_speed unchanged) ...
   average_speed         REAL,
-  kudos_count           INTEGER,
-  comment_count         INTEGER,
   gear_id               TEXT,
   trainer               INTEGER,
   commute               INTEGER,
   private               INTEGER,
   enriched_at           TEXT,
   detail_json           TEXT NOT NULL,
   fetched_at            TEXT NOT NULL
 );
 -- indexes recreated identically after rebuild:
 idx_activities_start_epoch, idx_activities_sport_type, idx_activities_enriched_at
```

## Enrichment unit (visibility definition)

- **Before**: `detail + laps + comments + kudos + zones + streams`
- **After**: `detail + laps + zones + streams`
- `enriched_at` is still stamped **last**, only after `streams` are persisted (streams visibility invariant unchanged). Activities already stamped stay visible (no regression).

## Repository surface deltas (`db/repositories/activities.py`)

- `_PROMOTED_KEYS`: remove `"kudos_count"`, `"comment_count"`.
- `_summary_view()`: remove `kudos_count`, `comment_count` keys from the returned dict (this is the field that any reader/dashboard receives).
- `enrich(...)`: remove `comments` and `kudos` parameters and their `_write_*` calls.
- Delete methods: `_write_comments`, `_write_kudos`, `comments`, `kudos`.

## Migration: ordered steps (`db/migrations.py`)

Guarded entry point, called from `engine.connect()` **before** `apply_schema()`. Runs only if legacy structures are present.

1. **Detect** (idempotency guard): legacy present if `comments` or `kudos` table exists, **or** `PRAGMA table_info(activities)` still lists `kudos_count`/`comment_count`. If absent → return (no-op).
2. `PRAGMA foreign_keys=OFF` (outside any transaction).
3. `BEGIN`
4. `DROP TABLE IF EXISTS comments;` `DROP TABLE IF EXISTS kudos;` (also removes their indexes).
5. Rebuild `activities`:
   - `CREATE TABLE activities_new ( … new column set … );`
   - `INSERT INTO activities_new (<kept cols>) SELECT <kept cols> FROM activities;`
   - `DROP TABLE activities;`
   - `ALTER TABLE activities_new RENAME TO activities;`
   - Recreate the three `activities` indexes.
6. `COMMIT`
7. `PRAGMA foreign_keys=ON;` then `PRAGMA foreign_key_check;` (must report no violations).

**Properties** (FR-015): guarded (legacy-only), idempotent (no-op on fresh/migrated DB), atomic (single transaction → crash rolls back), non-destructive to kept data and to `raw_responses`/`detail_json`.

## Validation rules

- Post-migration: `comments` and `kudos` tables do **not** exist; `PRAGMA table_info(activities)` has no `kudos_count`/`comment_count`; row counts for `activities` and all kept facet tables are unchanged from pre-migration.
- An upgraded DB and a freshly-created DB have identical `sqlite_master` table/column/index sets (SC-007).
- `raw_responses` row count is unchanged by the migration (archive preserved).
- Any activity with `enriched_at NOT NULL` before migration still has it after (SC-005).
