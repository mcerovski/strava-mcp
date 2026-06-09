# Quickstart / Validation: Unify Auth Token Storage

Runnable checks that prove the single-store, single-path model works end to end. Run from the
repo root. No live Strava calls are required except the one-time `auth` in scenario 3.

## Prerequisites

- `uv sync` completed; `.env` has `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET`.
- A scratch DB path for the negative tests, e.g. `STRAVA_DB_PATH=./.database/scratch.db`.

## Scenario 1 — No tokens → actionable error (FR-007, SC-003)

```bash
STRAVA_DB_PATH=./.database/scratch-empty.db uv run strava-mcp serve
```

**Expected**: exits non-zero, prints `run uv run strava-mcp auth`, logs
`insufficient scope (missing: …); refusing to serve`. (Identical to today, now with no env
fallback in play.)

## Scenario 2 — Legacy env token values are ignored (config-surface contract)

```bash
STRAVA_DB_PATH=./.database/scratch-empty.db \
STRAVA_ACCESS_TOKEN=should-be-ignored \
STRAVA_REFRESH_TOKEN=should-be-ignored \
uv run strava-mcp serve
```

**Expected**: same actionable error as Scenario 1 — the env values do **not** authorize the
server (previously they would have seeded it). Proves the seed is gone.

## Scenario 3 — Auth populates the single store, serve uses it (US1, US2)

```bash
uv run strava-mcp auth        # complete OAuth (prints URL if no browser)
uv run strava-mcp serve       # starts; uses the DB row
```

**Expected**: `auth` writes the `tokens` row; `serve` starts and serves on the loopback MCP port
using the stored token. No token value was ever placed in `.env`.

## Scenario 4 — No token secret in config (SC-002)

```bash
grep -E 'STRAVA_(ACCESS|REFRESH)_TOKEN|STRAVA_TOKEN_' .env.example   # → no matches
sudo docker compose config | grep -Ei 'access_token|refresh_token'  # → no token secret
```

**Expected**: no token fields in the shipped template; no token secret in the resolved compose
config.

## Scenario 5 — Automated tests (II. Testing Standards)

```bash
uv run pytest tests/unit/test_tokens.py -q
uv run pytest -q
```

**Expected**: the rewritten `test_tokens.py` asserts that with no DB row `current()` raises and
`read()` is the sole source; the full suite passes. Static checks (`uv run ruff check`,
type-check) are clean.

## Reference

- Token resolution behavior: [contracts/token-resolution.md](./contracts/token-resolution.md)
- Config surface: [contracts/config-surface.md](./contracts/config-surface.md)
- Entities & state: [data-model.md](./data-model.md)
