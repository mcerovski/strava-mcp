# strava-mcp

A locally-run [MCP](https://modelcontextprotocol.io) server that maintains a
complete local mirror of **one athlete's** Strava data and serves it to AI
agents as pure database reads.

It authorizes once, **backfills** your entire history newest→oldest (with full
per-activity **enrichment including streams**), then **polls** every 12 hours for
new activities. Agents query a local SQLite mirror over a loopback HTTP server —
the agent-facing tools **never call Strava**; only a background worker does.

## How it works

```
uv run strava-mcp auth       # one-time OAuth (full read scopes) → tokens stored in the DB
uv run strava-mcp serve      # MCP server (loopback) + background sync worker
uv run strava-mcp dashboard  # read-only local web UI over the mirror (loopback)
```

- **Backfill**: a single worker thread pages your activities newest→oldest,
  fetching each activity as one enriched unit (detail + laps +
  zones + streams + segment efforts) and writing it atomically. An activity
  becomes visible to agents only once it is **fully enriched** — partial data is
  never exposed.
- **Rate-limit discipline**: the worker stays within Strava's read budget
  (100/15 min, 1000/day) and, on exhaustion or a 429, **cools down to the known
  next reset** (the next quarter-hour or midnight UTC) rather than retry-looping.
  Backfill is checkpointed after every page and resumes with **zero re-fetch**.
- **Reality check**: a multi-year history legitimately takes **hours to days** to
  backfill, bounded by the rate limit. Use `sync_status()` to watch progress.
- **Poll**: once fully synced, the worker polls every 12 h with a 14-day
  lookback, dedupes by activity id, and **only inserts** new activities — it
  never mutates or deletes existing rows (read-only / insert-only by design).
- **Storage**: dual-write — verbatim API JSON into an append-only `raw_responses`
  store, plus lean normalized tables (indexed promoted columns + `detail_json`).

## Prerequisites

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).
- A Strava API application (`client_id` / `client_secret`) from
  <https://www.strava.com/settings/api>, with the callback domain allowing
  `127.0.0.1`.

## Setup

```bash
cp .env.example .env        # then fill in STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET
uv sync                     # install locked dependencies
```

Key settings (see `.env.example` for all):

| Var | Default | Purpose |
|-----|---------|---------|
| `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | — | App credentials (required). |
| `STRAVA_SCOPES` | `read,read_all,profile:read_all,activity:read,activity:read_all` | Requested read scopes. |
| `STRAVA_DB_PATH` | `./.database/strava.db` | SQLite mirror path. |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8720` | MCP HTTP bind (loopback only). |
| `OAUTH_REDIRECT_PORT` | `8721` | Local OAuth callback port. |
| `SYNC_MAX_REQUESTS` | `900` | Per-window request ceiling the worker self-limits to. |

Secrets live only under `.env` and `./.database/` (both gitignored) and are
**never logged**.

## Authorize

```bash
uv run strava-mcp auth
```

Opens Strava's consent screen for the full **read** scopes (prints the URL if
headless), auto-captures the redirect on `127.0.0.1`, stores the tokens in the
DB, and verifies with a one-activity probe read. Read scopes only — the mirror
never requests write access. If you uncheck a scope, `auth` warns which required
scope is missing.

## Serve

```bash
uv run strava-mcp serve
```

Refuses to start (printing `run uv run strava-mcp auth`) if the stored token
lacks a required scope. Otherwise it binds the FastMCP `streamable-http` server
to `http://127.0.0.1:8720` and starts the worker. It survives across agent
sessions and multiple clients may connect.

## Dashboard

```bash
uv run strava-mcp dashboard
```

A separate, **read-only** local web UI over the same mirror — run it alongside
`serve` (it reads via read-only connections and never blocks the sync worker, and
never calls Strava). It binds to `http://127.0.0.1:8722` (override with
`DASHBOARD_HOST` / `DASHBOARD_PORT`). Routes:

- `/` — filterable, paginated activity list (newest first; enriched activities only)
- `/activity/{id}` — summary, laps, segment efforts, HR/power zones, and inline-SVG
  stream graphs
- `/timeline?period=week|month|year` — aggregate training volume per period
- `/sync` — current backfill/poll progress (phase, frontier, %, counts, rate-limit
  budget, cooldown); reflects the latest persisted state on each page reload

The UI is fully offline (no external assets), shows no GPS map in v1, and renders
no tokens or secrets. If the mirror does not exist yet it prints
`run uv run strava-mcp serve` rather than failing opaquely.

## Run as a service (systemd)

To keep `serve` and the `dashboard` running on a VPS — restarting on crash and
starting on boot — install them as **user** systemd services. Two units run the
two commands independently from the project directory.

Create `~/.config/systemd/user/strava-mcp.service`:

```ini
[Unit]
Description=strava-mcp (MCP server + background sync worker)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/<user>/projects/strava-mcp
ExecStart=/home/<user>/.local/bin/uv run strava-mcp serve
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

And `~/.config/systemd/user/strava-mcp-dashboard.service` (identical, with
`ExecStart=… uv run strava-mcp dashboard` and a matching `Description`).

Enable and start them:

```bash
systemctl --user daemon-reload
systemctl --user enable --now strava-mcp.service strava-mcp-dashboard.service
systemctl --user status strava-mcp.service strava-mcp-dashboard.service
```

**Boot persistence (important):** user services only run while you have an active
login session unless **linger** is enabled. Without it the services stop on logout
and do **not** start after a reboot:

```bash
sudo loginctl enable-linger <user>     # start at boot, survive logout
loginctl show-user <user> -p Linger    # expect: Linger=yes
```

Useful operations:

```bash
journalctl --user -u strava-mcp -f                       # follow logs (also ./.database/strava-mcp.log)
systemctl --user restart strava-mcp strava-mcp-dashboard  # after pulling new code
```

> Restarting `serve` after an upgrade applies any pending schema migration to the
> mirror on first DB open (idempotent). Back up `.database/strava.db` before
> upgrades that change the schema.

## Connecting an MCP client

Point any MCP client at `http://127.0.0.1:8720` (streamable HTTP). Available read
tools:

- `get_athlete()`
- `list_activities(after?, before?, sport_type?, limit?)` · `get_activity(id)`
- `get_laps(id)` · `get_activity_zones(id)`
- `get_activity_streams(id, keys?)`
- `list_gear()` · `get_gear(id)`
- `list_routes()` · `get_route(id)`
- `list_starred_segments()` · `get_segment(id)` · `list_segment_efforts(segment_id)`
- `summarize_training(period, sport_type?)`
- `sync_status()` · `sync_now()`

Any activity the backfill frontier hasn't reached (or hasn't fully enriched)
returns `{ "status": "not_yet_synced", "id": <id> }`; an unknown id returns
`{ "status": "not_found", "id": <id> }`.

## Tests

```bash
uv run pytest            # offline + deterministic: temp SQLite (WAL) + recorded fixtures
uv run ruff check .      # lint
uv run mypy strava_mcp   # type check
```

No test contacts the live Strava API; fixtures derive from `strava-api-spec/`.
