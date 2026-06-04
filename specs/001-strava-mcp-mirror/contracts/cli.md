# Contract: CLI commands

Two entrypoints, run via `uv run strava-mcp <command>`. Sync runs **inside** `serve` (no
standalone sync command). Config is loaded from env / `.env` (`config.py`, see `.env.example`).

---

## `uv run strava-mcp auth`

The only human-in-the-loop step. Completes the full-scope OAuth authorization-code flow and
persists tokens in the DB.

**Behavior** (R5, R6; FR-001..FR-005)
1. Build the authorize URL from `STRAVA_SCOPES` (default: `read,read_all,profile:read_all,
   activity:read,activity:read_all`), `client_id`, `redirect_uri=http://127.0.0.1:${OAUTH_REDIRECT_PORT}`,
   `response_type=code`, a CSRF `state`.
2. Open it via the browser; **fall back to printing the URL** when headless.
3. Run a one-shot local callback server on `127.0.0.1:${OAUTH_REDIRECT_PORT}` that
   **auto-captures** `code` and the returned `scope` (no copy-paste).
4. Exchange `code` at `POST /oauth/token` (`grant_type=authorization_code`).
5. Persist `access_token, refresh_token, expires_at, scope` to the `tokens` table (DB row
   overrides `.env` seed thereafter).
6. **Verify** with `GET /athlete/activities?per_page=1` (expect HTTP 200) and report the
   granted scopes; warn if any required scope was unchecked by the user.

**Exit codes**
- `0` — tokens persisted and verification succeeded.
- non-zero — denied (`error=access_denied`), exchange failure, or verification failed.

**Acceptance mapping**: PLAN slice 1; US1 scenarios 1–3.

---

## `uv run strava-mcp serve`

Starts the FastMCP HTTP server (loopback) and the background sync worker thread. Does **not**
auto-launch auth.

**Behavior** (R6, R12; FR-006..FR-008, FR-009..FR-018, FR-023)
1. **Scope check**: read the stored token's scope. If any required read scope is missing,
   **exit non-zero** printing `run uv run strava-mcp auth` (no stack trace).
2. Open/initialize the SQLite DB at `STRAVA_DB_PATH` in **WAL** mode; apply schema.
3. Start the FastMCP `streamable-http` server bound to `MCP_HOST:MCP_PORT` (`127.0.0.1:8720`
   by default); register the read tools (contracts/mcp-tools.md).
4. Start the **single worker thread**: `BOOTSTRAP → BACKFILL (enrich incl. streams) → POLL`,
   self-throttling via the rate limiter, checkpointing after every page, resuming on restart.
5. **Log** progress (current activity, frontier date, rate-limit budget, cooldown ETA) to
   **stdout** and the rotating file `./.database/strava-mcp.log`; never log secrets.

**Runtime invariants**
- Worker is the **only writer**; tool calls are concurrent readers (WAL). No write contention.
- Tools never call Strava. Reads return `not yet synced` for unreached activities.
- Survives across agent sessions; multiple clients may connect.

**Exit codes**
- non-zero at boot — insufficient scope (with instructions) or DB/port failure.
- otherwise runs until interrupted (Ctrl-C / signal) — clean shutdown stops the worker.

**Acceptance mapping**: PLAN slices 2–8; US2..US8.

---

## Configuration (env / `.env`) — reference

| Var | Default | Purpose |
|-----|---------|---------|
| `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | — | App credentials (required). |
| `STRAVA_ACCESS_TOKEN` / `STRAVA_REFRESH_TOKEN` / `STRAVA_TOKEN_EXPIRES_AT` / `STRAVA_TOKEN_SCOPE` | — | Optional bootstrap seed (DB overrides once present). |
| `STRAVA_SCOPES` | `read,read_all,profile:read_all,activity:read,activity:read_all` | Requested OAuth scopes. |
| `OAUTH_REDIRECT_HOST` / `OAUTH_REDIRECT_PORT` | `127.0.0.1` / `8721` | Local callback. |
| `STRAVA_DB_PATH` | `./.database/strava.db` | SQLite path. |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8720` | MCP HTTP bind (loopback only). |
| `SYNC_MAX_REQUESTS` | `900` | Per-window request ceiling the worker self-limits to. |

Secrets live only under `./.database/` and `.env` (both gitignored); never logged.
