# Running strava-mcp with Docker / Dokploy

The stack ships as a single image run as three roles, wired together by
`docker-compose.yml`:

| Service     | Command             | Port | Role                                             |
|-------------|---------------------|------|--------------------------------------------------|
| `mcp`       | `strava-mcp serve`  | 8720 | FastMCP streamable-http server + sync worker (DB writer) |
| `dashboard` | `strava-mcp dashboard` | 8722 | Read-only web UI over the mirror (DB reader)  |
| `auth`      | `strava-mcp auth`   | 8721 | One-off interactive OAuth (profile `auth`)       |

> **There is no database container.** The mirror is embedded SQLite. The
> `strava-data` named volume (mounted at `/data` in every service) *is* the
> database — `mcp` is the only writer, `dashboard` reads the same file.

## 1. Configure secrets

Copy the template and fill in only the two Strava credentials — tokens are never
stored in `.env`, they live in the DB after `auth`:

```bash
cp .env.example .env
# set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET
```

Compose overrides the host bindings (`0.0.0.0`) and the DB/log paths (`/data/...`)
itself, so you do not need to touch those in `.env`.

## 2. Authorize once

`serve` refuses to start until a valid, full-scope token exists in the DB, so run
the OAuth flow once. It writes the token into the shared `strava-data` volume:

```bash
docker compose --profile auth run --rm --service-ports auth
```

The flow prints a Strava consent URL and waits for the redirect on port 8721.

- **Local machine:** set `OAUTH_REDIRECT_HOST=127.0.0.1` and open the printed URL
  in your browser; the callback returns to the published `127.0.0.1:8721`.
- **Remote server (Dokploy):** point your Strava app's *Authorization Callback
  Domain* (https://www.strava.com/settings/api) at the host/domain that resolves
  to the server, make port 8721 reachable for the duration of the flow, and open
  the consent URL from a browser that can reach it.

Alternatively, run `auth` on your laptop and copy the resulting `strava.db` into
the server's `strava-data` volume.

## 3. Run the stack

```bash
docker compose up -d --build
```

`dashboard` waits for `mcp` to become healthy (i.e. the DB exists and the server
is listening) before starting. The sync worker begins mirroring immediately.

- MCP endpoint: `http://<host>:8720`
- Dashboard: `http://<host>:8722`

## Dokploy notes

- Create a **Compose** application pointing at this repo; Dokploy builds from the
  `Dockerfile` and runs `docker-compose.yml`.
- Set `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` as Dokploy environment variables
  (or provide a `.env`).
- Prefer routing a Dokploy **domain** to container port `8720` (MCP) and `8722`
  (dashboard) via the UI instead of publishing host ports — you can then delete
  the `ports:` blocks from `docker-compose.yml` to avoid host-port conflicts with
  Traefik.
- Persist the `strava-data` volume in Dokploy's volume settings so the mirror and
  token survive redeploys.
