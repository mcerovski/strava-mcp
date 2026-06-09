# Quickstart: Validate Comments/Kudos Removal

How to prove the feature works end-to-end. Assumes `uv` is set up and the repo is on branch `003-remove-comments-kudos`.

## Prerequisites

- `uv sync` (dependencies installed)
- No live Strava calls needed — validation uses the existing fixture-based tests.

## 1. Automated validation (primary)

```bash
uv run pytest
```

Expected: green. Key suites that encode this feature's acceptance criteria:

- `tests/integration/test_migration_drop_comments_kudos.py` (NEW) — upgrade migration postconditions, idempotency, archive preservation, fresh-DB no-op. → SC-006, SC-007, FR-010/011/015.
- `tests/integration/test_enrichment.py`, `test_enrichment_streams_invariant.py` — enrichment now writes `detail + laps + zones + streams`; visibility still gated on streams; no comments/kudos written. → FR-001/002/003/004, SC-005.
- `tests/integration/test_dual_write.py` — every normalized row for the **remaining** facets has a backing raw row; comments/kudos no longer in the facet loop. → Principle I.
- `tests/contract/test_enrichment_tools.py`, `test_multi_client.py` — `get_comments`/`get_kudos` are absent from the tool set; remaining facet tools unchanged. → FR-006, contract delta.

## 2. Migration on a real pre-change database (manual spot check)

Simulate an existing deployment:

1. Check out the previous build, run a small fixture-backed sync (or use a seeded fixture DB) so the DB contains `comments`/`kudos` rows and non-null count columns.
2. Check out this branch and open the same DB (start `serve`, or just call `connect()`).
3. Verify with `sqlite3`:

```bash
sqlite3 .database/strava.db "SELECT name FROM sqlite_master WHERE name IN ('comments','kudos');"   # → empty
sqlite3 .database/strava.db "PRAGMA table_info(activities);" | grep -E 'kudos_count|comment_count'  # → empty
sqlite3 .database/strava.db "SELECT count(*) FROM raw_responses WHERE resource_type IN ('comments','kudos');"  # → unchanged (>0 if any existed)
sqlite3 .database/strava.db "PRAGMA foreign_key_check;"   # → empty (no violations)
```

Expected: no `comments`/`kudos` tables, no count columns, raw archive intact, server starts and serves previously synced activities. → User Story 3.

## 3. Faster-sync sanity (request count)

Run the enrichment test that counts requests per activity and confirm two fewer calls per activity (no `…/comments`, no `…/kudos`). The per-activity enrichment issues `detail`, `laps`, `zones`, `streams` only. → SC-001 (6 → 4), US1.

## 4. Surface audit (nothing remains)

```bash
grep -rin --include=*.py --include=*.sql --include=*.html "kudos\|comment" strava_mcp/
```

Expected: no references in active server/sync/dashboard/schema surfaces (matches lean removal). Constitution/CONTEXT/docs updated to the redefined enrichment unit. → FR-007/008/009, SC-004.

## Done

All four checks pass ⇒ comments/kudos are fully removed, existing servers upgrade cleanly, and per-activity sync cost drops from 6 to 4 read requests.
