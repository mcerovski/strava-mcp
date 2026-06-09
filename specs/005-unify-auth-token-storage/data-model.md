# Phase 1 Data Model: Unify Auth Token Storage

No persistent schema change. This documents the credential entities and the (simplified) state
transitions of token resolution.

## Entities

### Token Record (persisted)

The single row of the existing `tokens` table — the **sole source of truth** for credentials.

| Field | Type | Notes |
|-------|------|-------|
| `id` | int | Always `1` (single-row table) |
| `access_token` | text | Bearer token; short-lived, refreshed in place |
| `refresh_token` | text | Used to mint new access tokens; may be rotated by Strava |
| `expires_at` | int (epoch) | Access-token expiry; drives near-expiry refresh |
| `scope` | text | Granted scopes; checked by `serve` at startup |
| `updated_at` | text (iso) | Last write time |

**Validation / rules**:
- A record is *usable* only if `access_token` and `refresh_token` are both present.
- Refresh **preserves** `scope` (Strava does not echo it on refresh) and **persists** any rotated
  `refresh_token` back to this same row.
- This row is written **only** by the `auth` flow (initial) and by `TokenStore.refresh()`
  (rotation). No other writer.

### App Client Credentials (config, not a token)

| Field | Source | Used for |
|-------|--------|----------|
| `strava_client_id` | `.env` / env | OAuth authorize + token refresh |
| `strava_client_secret` | `.env` / env | OAuth authorize + token refresh |

These remain in configuration. They are **not** credentials/tokens and are never stored in the
`tokens` row.

### REMOVED — Env Token Seed

Deleted entirely (no longer part of the model):

- `Settings.strava_access_token`
- `Settings.strava_refresh_token`
- `Settings.strava_token_expires_at`
- `Settings.strava_token_scope`
- `auth/tokens.py::_seed_from_env()`
- `mcp/server.py::_seed_tokens()`

## Token-Resolution State (simplified)

### Before (current)

```
active token = DB row  IF present
             ELSE env seed  IF strava_access_token AND strava_refresh_token present
             ELSE (none) → error / all-scopes-missing
```
Two readers implement this fallback independently (`current()` and `check_scopes`).

### After (this feature)

```
active token = DB row  IF present
             ELSE (none) → actionable error / all-scopes-missing
```

| Consumer | Call | "No row" outcome |
|----------|------|------------------|
| Worker token provider (`TokenStore.access_token` → `current()`) | `read()` or raise | raises `RuntimeError("No tokens available; run \`uv run strava-mcp auth\`.")` |
| `serve` startup gate (`mcp/server.py::check_scopes`) | `read()` directly | returns all `REQUIRED_SCOPES` as missing → prints `run uv run strava-mcp auth`, exits 1 |
| `auth` flow | `TokenStore.save()` | writes the row (unchanged) |

There is now exactly **one** token source (`read()`) and **no** env-fallback branch.
