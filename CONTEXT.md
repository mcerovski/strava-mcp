# strava-mcp

A locally-run MCP server that maintains a complete local mirror of one athlete's
Strava data and serves it to AI agents as pure database reads. This glossary fixes
the shared language; the spec lives in [PRD.md](./PRD.md).

## Language

### Sync vocabulary

**Backfill**:
The one-time, newest→oldest sweep that builds the complete local mirror. Self-throttling
and self-resuming around rate limits. Runs until it reaches the athlete's first-ever activity.
_Avoid_: import, initial sync, full sync (use "backfill").

**Frontier**:
The oldest activity the backfill has reached so far. Moves backwards in time as the backfill
progresses. The complement is the **newest-synced** cursor used by the poll.
_Avoid_: cursor (ambiguous — name which one), checkpoint.

**Poll**:
The steady-state, every-12-hours forward check for *new* activities once backfill is complete.
Lists with a 14-day lookback and dedupes by activity id (so back-dated uploads are caught),
then only inserts ids not already stored — it never mutates existing rows.
_Avoid_: refresh, update, re-sync.

**Fully synced**:
The terminal state where the frontier has reached the first-ever activity and every activity
carries its full enrichment including streams. Only then does the worker switch to polling.
_Avoid_: "done", "up to date" (ambiguous with poll).

**Enrichment**:
The complete per-activity data set fetched as one unit when the frontier reaches an activity:
DetailedActivity + laps + zones + streams. An activity is written only when
fully enriched — partially-enriched activities are never visible.
_Avoid_: details, hydration.

### Strava domain (as used here)

**Activity**:
A single recorded workout owned by the authenticated athlete (a run, ride, swim…). The central
entity. Carries summary fields always; full enrichment once the backfill reaches it.

**Stream**:
The raw per-sample time series for an activity (heartrate, watts, latlng, altitude, cadence,
velocity, grade, temp, moving, time, distance). The bulk of the stored data by volume.
_Avoid_: samples, telemetry, raw data (overloaded with the raw-JSON store).

**Segment effort**:
One attempt by the athlete at a Strava **segment** during an activity. Distinct from the
segment itself.
_Avoid_: "segment" (the effort is the attempt, not the segment).

**Athlete**:
The single Strava account this database mirrors. One athlete per database — there is no
multi-athlete concept.
_Avoid_: user, account.

### Storage vocabulary

**Raw store**:
The append-only `raw_responses` table holding verbatim API JSON, kept as a backup independent
of the normalized tables. "Raw" refers to this store specifically.
_Avoid_: cache, blob store.

## Example dialogue

> **Dev:** When the agent asks for a 2015 ride on day one, do we fetch it live?
> **Domain:** No — there's no live fetch. The agent sees an activity only after the **backfill**
> **frontier** reaches it. Until then the tool returns "not yet synced".
> **Dev:** So a freshly recorded ride from this morning?
> **Domain:** That's the **poll's** job, not the backfill's — but only once we're **fully synced**.
> During backfill the frontier is moving *backwards*, so today's ride is picked up by the very
> first backfill page anyway (newest-first). Either way it arrives **enriched** — summary,
> laps, zones, and **streams** together, never half.
