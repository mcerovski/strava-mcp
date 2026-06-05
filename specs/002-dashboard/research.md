# Phase 0 Research: Local Data Dashboard

All Technical Context unknowns are resolved here. The spec's two deferred-to-planning items (UI
rendering approach and default port) and the recurring constraint (no external network) are the main
decisions. No `NEEDS CLARIFICATION` markers remain.

---

## R1 — HTTP serving mechanism

**Decision**: Use the Python standard library `http.server.ThreadingHTTPServer` with a small explicit
path router, bound to `127.0.0.1`. No third-party web framework.

**Rationale**:
- **Zero new dependency** — honors the constitution's "complexity is justified or removed" (YAGNI) and
  the "no new top-level dependency without justification" posture. The dashboard is a single-user, local,
  read-only surface with ~5 routes; a full framework is unjustified.
- `ThreadingHTTPServer` handles the handful of concurrent requests a single human browser issues; each
  request opens its **own read-only SQLite connection** (`engine.read_only_connect`), exactly mirroring
  the proven per-call MCP read pattern, so the sync worker is never blocked (Constitution IV, SC-005).
- Loopback bind is a one-liner (`("127.0.0.1", port)`), satisfying the mandatory loopback rule.

**Alternatives considered**:
- *Starlette + uvicorn* (already transitive via `fastmcp`): more capable/async, but couples the
  dashboard to the MCP server's transitive stack and adds async complexity for no functional gain at
  this scale. Rejected as over-engineering.
- *Flask / FastAPI*: a new top-level dependency for a trivial local server. Rejected.

---

## R2 — UI rendering approach (deferred from spec)

**Decision**: Server-rendered HTML. Pages are built by small Python templating helpers
(`render.py`) with strict `html.escape` on all dynamic text. Interaction (filtering, week/month/year
grouping, pagination) is driven entirely by **query-string parameters** on plain links/forms — no
client-side JavaScript framework, no build step.

**Rationale**:
- The spec needs **no live interactivity**: sync progress is page-load/manual-reload only (clarified —
  no auto-refresh), and filters/grouping map cleanly to GET parameters.
- A server-rendered approach keeps everything **offline** (no CDN, no npm/build toolchain) and keeps the
  module a thin, testable reader. Handlers return HTML strings that tests can assert against.

**Alternatives considered**:
- *Single-page app (React/Vue)*: build pipeline, bundlers, and a JS dependency tree — disproportionate
  for a local single-user viewer and hard to keep offline. Rejected.
- *Vendored JS charting + HTML*: see R3; rejected in favor of inline SVG to stay JS-free.
- *Jinja2 templating*: a reasonable single dependency, but with ~5 simple pages the helper-function
  approach avoids even that. Revisit only if template complexity grows.

---

## R3 — Charts without an external/JS dependency

**Decision**: Generate **inline SVG** line charts in Python (`charts.py`) directly from the stored
streams. One chart per present stream type (heart rate, power, speed/pace, altitude, cadence), plotted
against time or distance. Streams are **downsampled** to a bounded number of points (target ≈ 800–1200,
e.g. via min/max bucketing or stride) before emitting SVG.

**Rationale**:
- **No external network** (no CDN-hosted charting lib) and **no JavaScript** — fully aligned with the
  loopback/offline posture and keeps the page self-contained.
- Downsampling bounds SVG size regardless of activity length, meeting the < 2s render target (SC-003)
  and the "streams are the bulk — handle efficiently" rule (Constitution IV).
- Inline SVG is trivially unit-testable (assert path/point counts, axis labels, units).

**Alternatives considered**:
- *uPlot/Chart.js vendored locally*: nicer interactivity but adds a vendored asset + a little JS; not
  needed for static graphs. Rejected for v1 (can revisit if interactive zoom is wanted later).
- *Server-rendered PNG (matplotlib)*: heavy new dependency and slower; rejected.

---

## R4 — GPS route maps (clarified out of scope)

**Decision**: No map rendering in v1. The detail view shows graphs and tabular data only.

**Rationale**: Map tiles require an external tile service (or a large bundled tileset), which conflicts
with the no-external-network posture. Confirmed deferred during clarification (2026-06-05). Stored
`latlng` stream data may later feed an offline map feature, tracked separately.

---

## R5 — Sync-progress freshness (clarified)

**Decision**: The sync-progress page reads `sync_state` (plus cheap COUNTs) at request time and renders
the current persisted state. No background auto-refresh; the user reloads to see newer figures.

**Rationale**: Clarified 2026-06-05. A request-time read reuses the exact logic already proven in the
`sync_status` MCP tool (phase, frontier, percent-complete, counts, rate-limit budget, cooldown),
keeping a single source of truth for how progress is computed. Avoids websockets/polling complexity.

---

## R6 — Data access layer

**Decision**: All reads go through the `repositories/` layer via read-only connections. Extend
repositories with the few read methods the dashboard needs:
- `ActivitiesRepository.list_page(*, filters, limit, offset)` + `count_enriched(filters)` — paginated,
  visibility-aware list with a total count for pager UI (FR-004/005/015).
- `ActivitiesRepository.training_rollup(period, sport_type)` supporting `weekly | monthly | yearly` —
  SQL `strftime` group-by extending the existing `summarize_training` pattern with a yearly bucket
  (FR-009/010). `summarize_training` may delegate to this shared method to avoid duplicated SQL.
- An `efforts_for_activity(activity_id)` read (homed in `SegmentsRepository`, alongside the existing
  `efforts_for_segment`) for the detail view (FR-007).
- Existing methods reused as-is: `get_detail`, `laps`, `zones`, `status`, `count*`,
  `StreamsRepository.read/has_streams`, `AthleteRepository.read`.

**Rationale**: Keeps SQL in the sanctioned repositories layer (Constitution I "typed boundaries"); the
dashboard `queries.py` only *composes* repository calls. Empty timeline buckets (gaps in training,
US3 scenario 3) are filled in Python between the min and max returned period — a presentation concern,
not stored data.

**Alternatives considered**:
- *Import `strava_mcp.mcp.tools` read functions directly*: would couple the dashboard to the MCP module
  (two sibling readers should not depend on each other). Rejected in favor of shared repository methods.
- *Ad-hoc SQL in handlers*: violates the typed-boundary rule. Rejected.

---

## R7 — CLI & configuration

**Decision**: Add a `dashboard` subcommand to `__main__.py`, lazily importing the dashboard stack
(like `serve` does). Add `dashboard_host` (default `127.0.0.1`) and `dashboard_port`
(default `8722`, adjacent to MCP `8720` / OAuth `8721`) to `Settings`.

**Rationale**: Consistent with the existing `auth`/`serve` wiring and lazy-import discipline; the
default port avoids the two ports already in use. Loopback default enforces the security constraint.

**Alternatives considered**: A separate console-script entrypoint — unnecessary; a subcommand matches
the documented `uv run strava-mcp <command>` contract.

---

## R8 — Failure modes (actionable, per Constitution III)

**Decision**:
- **DB missing/unreadable**: `read_only_connect` raises (the file must already exist). Catch at startup
  and exit with a concrete message, e.g. *"No mirror found at <path>. Run `uv run strava-mcp serve`
  first to create and populate it."* — not a stack trace.
- **Port in use**: catch `OSError` on bind and print *"Port <n> is in use. Set DASHBOARD_PORT to a free
  port and retry."*
- **Empty mirror / no streams / worker not running**: render informative empty/degraded states per view
  (FR-013), never an error page.

**Rationale**: Mirrors the established `run uv run strava-mcp auth` actionable-failure pattern.
