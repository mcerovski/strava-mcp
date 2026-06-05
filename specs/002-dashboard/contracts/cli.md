# CLI Contract: `dashboard` subcommand

Extends the existing `uv run strava-mcp <command>` surface (alongside `auth` and `serve`).

## Command

```
uv run strava-mcp dashboard
```

Starts the local, read-only dashboard HTTP server and blocks until interrupted (Ctrl-C), like `serve`.
The dashboard stack is **lazily imported** inside the command handler so `auth`/`serve` do not pull it
in (matching the existing pattern).

## Configuration (env / `.env`)

| Setting | Env var | Default | Notes |
|---------|---------|---------|-------|
| Bind host | `DASHBOARD_HOST` | `127.0.0.1` | Loopback only (mandatory; do not expose externally). |
| Bind port | `DASHBOARD_PORT` | `8722` | Adjacent to MCP `8720` / OAuth `8721`. |
| DB path | `STRAVA_DB_PATH` | `./.database/strava.db` | Reuses the existing setting; opened read-only. |

## Behavior

- On start, the dashboard opens a **read-only** connection to the existing mirror. It performs **no**
  Strava calls and **no** writes.
- It binds to `DASHBOARD_HOST:DASHBOARD_PORT` and prints the URL, e.g.
  `dashboard on http://127.0.0.1:8722`.
- It runs concurrently with `serve` (separate process) without blocking the sync worker (read-only WAL
  connections per request).

## Exit codes & actionable failures

| Condition | Behavior | Exit |
|-----------|----------|------|
| Mirror DB not found / unreadable | Print: `No mirror found at <path>. Run 'uv run strava-mcp serve' first to create and populate it.` | `1` |
| Port already in use (`OSError` on bind) | Print: `Port <n> is in use. Set DASHBOARD_PORT to a free port and retry.` | `1` |
| Normal start | Print bind URL; serve until Ctrl-C | `0` on clean shutdown |

Errors are concrete operator instructions, never a stack trace (Constitution III).

## Non-goals

- No write commands, no Strava interaction, no token handling for API use (and no token/secret is ever
  rendered).
- No authentication layer (single-user loopback, consistent with `serve`).
