# Contract: Configuration Surface

The configuration surface after this feature. Verified by inspection of `Settings` /
`.env.example` and the existing config tests.

## Removed settings (deleted from `Settings` and `.env.example`)

| Field | Env var |
|-------|---------|
| `strava_access_token` | `STRAVA_ACCESS_TOKEN` |
| `strava_refresh_token` | `STRAVA_REFRESH_TOKEN` |
| `strava_token_expires_at` | `STRAVA_TOKEN_EXPIRES_AT` |
| `strava_token_scope` | `STRAVA_TOKEN_SCOPE` |

After removal, `Settings` exposes **no** Strava token field.

## Retained credential settings

| Field | Env var | Required for |
|-------|---------|--------------|
| `strava_client_id` | `STRAVA_CLIENT_ID` | OAuth authorize + token refresh |
| `strava_client_secret` | `STRAVA_CLIENT_SECRET` | OAuth authorize + token refresh |

(Other settings — scopes, redirect host/port, DB path, MCP/dashboard host/port, sync tuning —
are unchanged.)

## Behavior with legacy keys present

- `Settings` uses pydantic-settings with `extra="ignore"`. A `.env` that still lists the removed
  `STRAVA_*_TOKEN*` keys loads **without error**; the values are ignored. Supporting this is not
  a goal (existing installs are out of scope) — it is a harmless side effect.

## Contract checks

- `Settings()` constructed from a `.env` containing the four removed keys → loads successfully and
  exposes no token attributes for them.
- `.env.example` contains `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` and **no** token lines.
- `docker compose config` for a default install shows no Strava token secret.
