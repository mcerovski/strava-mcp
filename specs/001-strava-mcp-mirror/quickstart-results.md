# Quickstart Validation Results

Run of the [quickstart.md](./quickstart.md) scenarios against recorded fixtures
(offline, deterministic — Constitution II). All Strava interactions use fixtures
derived from `strava-api-spec/`; no scenario contacts the live API.

**Command**: `uv run pytest` · **Result**: ✅ **79 passed** · `ruff check .` clean ·
`mypy strava_mcp` clean.

## Scenario → covering test(s)

| # | Scenario (quickstart.md) | Covering test(s) | Status |
|---|--------------------------|------------------|--------|
| 1 | Authorize once (US1) | `tests/contract/test_cli_auth.py`, `tests/unit/test_tokens.py` | ✅ |
| 2 | Serve + athlete read (US2) | `tests/contract/test_serve_athlete.py`, `tests/integration/test_bootstrap_athlete.py`, `test_quickstart.py` | ✅ |
| 3 | Activity backfill, filters, resume, status (US3) | `tests/integration/test_backfill.py`, `test_backfill_complete.py`, `tests/contract/test_activities_tools.py`, `tests/unit/test_ratelimit.py` | ✅ |
| 4 | Enrichment facets (US4) | `tests/integration/test_enrichment.py`, `tests/contract/test_enrichment_tools.py` | ✅ |
| 5 | Streams + fully-synced (US5) | `tests/integration/test_streams.py`, `test_enrichment_streams_invariant.py`, `tests/contract/test_streams_tool.py` | ✅ |
| 6 | Gear, routes, starred segments (US6) | `tests/integration/test_bootstrap_resources.py`, `tests/contract/test_resources_tools.py` | ✅ |
| 7 | Steady-state poll + nudge (US7) | `tests/integration/test_poll.py`, `tests/contract/test_sync_now.py` | ✅ |
| 8 | Training summary (US8) | `tests/contract/test_summaries.py` | ✅ |
| — | Full end-to-end lifecycle (scenarios 2–8) | `tests/integration/test_quickstart.py` | ✅ |

## Cross-cutting invariants (Polish, Phase 11)

| Invariant | Test | Status |
|-----------|------|--------|
| Tools never import `client`/`sync` (pure readers) | `tests/contract/test_pure_reader.py` | ✅ |
| Dual-write: every normalized row has a backing raw row | `tests/integration/test_dual_write.py` | ✅ |
| Vocabulary discipline (CONTEXT.md terms) | `tests/unit/test_vocabulary.py` | ✅ |
| Log redaction — no secrets to stdout/file | `tests/unit/test_log_redaction.py` | ✅ |
| Concurrent reads during writes (WAL) | `tests/integration/test_concurrent_read.py` | ✅ |
| Multiple MCP clients / sessions | `tests/contract/test_multi_client.py` | ✅ |

## Notes

- Activities are visible only when fully enriched **including streams**; pending
  and unknown activities return `not_yet_synced` / `not_found` (verified in
  `test_quickstart.py::test_quickstart_pending_activity_is_invisible`).
- Backfill cooldown is exercised with synthesized rate-limit errors + an
  injectable clock (no real sleeping), proving deterministic resume.
