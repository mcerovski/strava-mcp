# Lean promoted columns + `detail_json`, not a full relational mirror

Normalized tables carry only the fields agents filter/sort/aggregate on as indexed columns;
everything else lives in a `detail_json` column holding the full parsed object. The append-only
`raw_responses` store keeps verbatim API JSON as the complete backup.

## Why

Strava's models are wide (~50 fields) and nested (`map`, `splits`, `segment_efforts[]`).
Mirroring every scalar as a column means brittle tables that need a migration each time Strava
adds a field, duplicating data the raw store already holds. Lean columns + JSON is resilient
(new fields just land in JSON), keeps queries fast on the fields that matter, and stays
queryable on the rest via SQLite `json_extract`.

## Consequences

- Filtering on an unpromoted field is unindexed (`json_extract`); the promoted set can be
  widened cheaply later.
- Independently-queried nested collections (`laps`, `segment_efforts`) get their own lean
  tables; one-off blobs (`map`, `photos`, `splits`) stay in the parent's `detail_json`.
