# Insert-only sync with a 14-day poll lookback

The steady-state POLL never mutates or re-fetches existing rows. It lists
`/athlete/activities?after = newest_synced − 14 days` and dedupes by activity id, inserting
only ids not already stored. Edits and deletes made on Strava are **not** reconciled.

## Why

Strava's `after`/`before` filter keys on an activity's `start_date`, not its upload time. A
strict insert-only cursor at the newest start_date would permanently miss back-dated uploads
(delayed device sync, manual entries, bulk imports) whose start_date predates the cursor. A
14-day lookback + dedupe-by-id catches realistically back-dated uploads at near-zero cost
(a few dozen already-stored activities re-listed and skipped every 12h) while staying
insert-only — it only ever *adds* missed activities.

Edit/delete reconciliation was rejected: it requires re-fetching activities (expensive against
rate limits) and the only real-time signal is webhooks, which need a public callback this local
tool intentionally avoids.

## Consequences

- Activities uploaded with a start_date older than 14 days behind the cursor are still missed.
- Title/type/privacy edits and deletions on Strava are not reflected in the mirror.
