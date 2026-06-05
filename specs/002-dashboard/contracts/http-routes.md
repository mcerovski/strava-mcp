# HTTP Routes Contract: Dashboard UI

The dashboard's interface is a small set of **GET** routes served on loopback. All responses are
server-rendered HTML (`text/html`) except the stylesheet. No route writes data or calls Strava. All
dynamic text is HTML-escaped. Unknown paths return `404` with an HTML message.

Maps to: FR-001/004/005/006/007/008/009/010/011/012/013/015/016/018, US1–US4.

---

## `GET /` — Activity list (US1, P1)

The landing page. Renders the athlete header (FR-018) + a newest-first, paginated, filterable list of
**enriched-only** activities (FR-004/005/006).

**Query parameters** (all optional):

| Param | Type | Meaning |
|-------|------|---------|
| `sport_type` | string | exact-match filter (indexed) |
| `after` | ISO date | start-date lower bound (inclusive) |
| `before` | ISO date | start-date upper bound (inclusive) |
| `page` | int ≥ 1 | pagination (page size = 50; via LIMIT/OFFSET) |

**Renders**: list rows (`ActivityListItem`), the active filters, a result count, and prev/next page
links. **Empty mirror or no matches** → an informative empty state, not an error (FR-013).

---

## `GET /activity/{id}` — Activity detail (US2, P2)

The deep dive for one activity (FR-007/008/008a).

**Renders**, for an enriched activity:
- summary metrics (from `detail_json`),
- laps table (omitted if none),
- segment efforts table (omitted if none),
- HR/power zone distribution (omitted if none),
- one inline-SVG line chart per **present** stream type; **"no stream data"** note if the streams row
  is absent.

**States**:
- id absent or not yet enriched → `404` with a "not found / not yet synced" HTML message (consistent
  with the partial-data rule — a listed-but-pending activity is treated as not visible).

---

## `GET /timeline` — Week/month/year timeline (US3, P3)

Aggregate training volume over time (FR-009/010).

**Query parameters**:

| Param | Type | Default | Meaning |
|-------|------|---------|---------|
| `period` | `week` \| `month` \| `year` | `month` | bucket grouping |
| `sport_type` | string | (all) | optional filter |

**Renders**: a table/bar view of `TimelineBucket`s (count, distance, moving time, elevation), newest
period first, with **zero buckets shown for empty periods** between the first and last bucket so gaps
are visible (US3 scenario 3). Switching `period` recomputes server-side via a link/select.

---

## `GET /sync` — Sync progress (US4, P4)

Renders `SyncProgressView` from `sync_state` + cheap COUNTs at request time (FR-011/012): phase,
frontier date, percent-complete estimate, stored-activity count, rate-limit budget, and cooldown ETA
when applicable. **No auto-refresh** — a manual reload reflects the latest persisted state. If the
worker is not running, shows the last persisted state.

---

## `GET /static/app.css` — Stylesheet

Serves the single bundled local stylesheet (`text/css`). No external/CDN assets are referenced anywhere
in the rendered HTML (no-external-network posture). No other static assets are required (charts are
inline SVG).

---

## Cross-cutting guarantees

- **Read-only**: every route opens its own `mode=ro` SQLite connection; none take a write lock or block
  the worker (Constitution IV, SC-005).
- **Visibility**: no route ever surfaces a non-enriched activity (SC-006).
- **No Strava calls**: zero outbound Strava requests originate from the dashboard process (SC-006).
- **Vocabulary**: all labels/status text use the fixed terms (backfill, frontier, poll, fully synced,
  enrichment, activity, stream, segment effort, athlete).
- **Secrets**: no token or secret is ever included in any response.
