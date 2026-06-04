# Pure-reader MCP server + single unified background backfill

We mirror all Strava data via **one eager background worker** (BOOTSTRAP → newest→oldest
BACKFILL with full per-activity enrichment *including streams* → 12h POLL), and MCP tools
are **pure reads against SQLite that never call Strava**. An activity is invisible to the
agent until the backfill has reached and fully enriched it (`get_*` returns "not yet synced").

## Why

We rejected lazy/on-demand fetching (fetch-and-cache when an agent first asks). A unified
backfill means exactly one code path that touches the API, the serving layer needs no live
API client or rate limiter, and "what's in the DB" is always a complete unit. The cost — the
agent can't see old history until the crawl reaches it — was explicitly accepted by the owner
("I don't need instant access to old activities").

## Consequences

- The serving side has no rate-limit or token-refresh concerns; only the worker does.
- Backfill of a multi-year history takes days of unattended crawling (rate limits); recent
  activities are available first because the sweep goes newest→oldest.
