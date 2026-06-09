-- Strava MCP Local Mirror schema (data-model.md).
-- Dual-write pattern: every fetched resource is written verbatim into the
-- append-only raw_responses store AND into a lean normalized table
-- (keys + promoted indexed columns + detail_json). WAL, single writer.

-- ---------------------------------------------------------------------------
-- Raw store (append-only backup) -- ADR 0002
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_responses (
  id            INTEGER PRIMARY KEY,
  resource_type TEXT NOT NULL,
  resource_id   TEXT,
  endpoint      TEXT NOT NULL,
  fetched_at    TEXT NOT NULL,
  payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_responses_resource
  ON raw_responses(resource_type, resource_id);

-- ---------------------------------------------------------------------------
-- tokens (single row) -- R4
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tokens (
  id            INTEGER PRIMARY KEY CHECK (id = 1),
  access_token  TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  expires_at    INTEGER NOT NULL,
  scope         TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- athlete (single row)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS athlete (
  id           INTEGER PRIMARY KEY,
  username     TEXT,
  firstname    TEXT,
  lastname     TEXT,
  detail_json  TEXT NOT NULL,
  zones_json   TEXT,
  stats_json   TEXT,
  fetched_at   TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- activities (central) -- R8
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activities (
  id                    INTEGER PRIMARY KEY,
  start_date            TEXT,
  start_date_epoch      INTEGER,
  start_date_local      TEXT,
  sport_type            TEXT,
  name                  TEXT,
  distance              REAL,
  moving_time           INTEGER,
  elapsed_time          INTEGER,
  total_elevation_gain  REAL,
  average_heartrate     REAL,
  max_heartrate         REAL,
  average_watts         REAL,
  max_watts             REAL,
  average_speed         REAL,
  gear_id               TEXT,
  trainer               INTEGER,
  commute               INTEGER,
  private               INTEGER,
  enriched_at           TEXT,
  detail_json           TEXT NOT NULL,
  fetched_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activities_start_epoch ON activities(start_date_epoch);
CREATE INDEX IF NOT EXISTS idx_activities_sport_type  ON activities(sport_type);
CREATE INDEX IF NOT EXISTS idx_activities_enriched_at ON activities(enriched_at);

-- ---------------------------------------------------------------------------
-- activity_streams (1:1 with activity) -- R7
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activity_streams (
  activity_id   INTEGER PRIMARY KEY REFERENCES activities(id),
  streams_json  TEXT NOT NULL,
  types         TEXT,
  fetched_at    TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- laps
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS laps (
  id            INTEGER PRIMARY KEY,
  activity_id   INTEGER REFERENCES activities(id),
  lap_index     INTEGER,
  detail_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_laps_activity ON laps(activity_id);

-- ---------------------------------------------------------------------------
-- activity_zones
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activity_zones (
  activity_id   INTEGER REFERENCES activities(id),
  zone_type     TEXT,
  detail_json   TEXT NOT NULL,
  PRIMARY KEY (activity_id, zone_type)
);

-- ---------------------------------------------------------------------------
-- segment_efforts (populated from embedded activity data) -- ADR 0001
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS segment_efforts (
  id               INTEGER PRIMARY KEY,
  segment_id       INTEGER,
  activity_id      INTEGER REFERENCES activities(id),
  start_date       TEXT,
  start_date_epoch INTEGER,
  elapsed_time     INTEGER,
  moving_time      INTEGER,
  detail_json      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segment_efforts_segment  ON segment_efforts(segment_id);
CREATE INDEX IF NOT EXISTS idx_segment_efforts_activity ON segment_efforts(activity_id);

-- ---------------------------------------------------------------------------
-- segments (starred = full detail; encountered = embedded summary)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS segments (
  id            INTEGER PRIMARY KEY,
  name          TEXT,
  starred       INTEGER NOT NULL,
  detail_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_starred ON segments(starred);

-- ---------------------------------------------------------------------------
-- gear
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gear (
  id            TEXT PRIMARY KEY,
  name          TEXT,
  type          TEXT,
  detail_json   TEXT NOT NULL,
  fetched_at    TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- routes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS routes (
  id            TEXT PRIMARY KEY,
  name          TEXT,
  type          INTEGER,
  distance      REAL,
  detail_json   TEXT NOT NULL,
  fetched_at    TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- sync_state (single row) -- R9
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sync_state (
  id                      INTEGER PRIMARY KEY CHECK (id = 1),
  phase                   TEXT NOT NULL,
  backfill_frontier_epoch INTEGER,
  newest_synced_epoch     INTEGER,
  backfill_complete       INTEGER NOT NULL DEFAULT 0,
  last_poll_at            TEXT,
  cooldown_until          TEXT,
  rate_limit_json         TEXT,
  run_log_json            TEXT,
  updated_at              TEXT NOT NULL
);
