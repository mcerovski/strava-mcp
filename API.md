# Strava API v3 Reference

Comprehensive documentation of the Strava REST API, compiled from the official
sources:

- Developer portal & docs: <https://developers.strava.com/>
- Reference / playground: <https://developers.strava.com/docs/reference/>
- Community reference mirror: <https://appsforstrava.com/developers/api-reference/>

The machine-readable specification (Swagger 2.0 / OpenAPI) is committed
alongside this file in [`strava-api-spec/`](./strava-api-spec/). The canonical
entry point is `strava-api-spec/swagger/swagger.json`; model definitions are
split into sibling files (`activity.json`, `athlete.json`, etc.) and referenced
by `$ref`.

| Property | Value |
|----------|-------|
| Spec format | Swagger 2.0 |
| API title | Strava API v3 |
| API version | 3.0.0 |
| Host | `www.strava.com` |
| Base path | `/api/v3` |
| Base URL | `https://www.strava.com/api/v3` |
| Schemes | HTTPS only |
| Produces | `application/json` |
| Auth | OAuth 2.0 (Bearer token) |

---

## Table of contents

1. [Authentication (OAuth 2.0)](#1-authentication-oauth-20)
2. [Scopes](#2-scopes)
3. [Rate limits](#3-rate-limits)
4. [Endpoints](#4-endpoints)
   - [Athletes](#41-athletes)
   - [Activities](#42-activities)
   - [Clubs](#43-clubs)
   - [Gear](#44-gear)
   - [Routes](#45-routes)
   - [Segments](#46-segments)
   - [Segment Efforts](#47-segment-efforts)
   - [Streams](#48-streams)
   - [Uploads](#49-uploads)
5. [Webhook Events API](#5-webhook-events-api)
6. [Data models](#6-data-models)
7. [Errors](#7-errors)
8. [The OpenAPI specification files](#8-the-openapi-specification-files)

---

## 1. Authentication (OAuth 2.0)

Strava uses the OAuth 2.0 **authorization code** flow. Every API request must
carry a short-lived access token in the header:

```
Authorization: Bearer <access_token>
```

Register an application at <https://www.strava.com/settings/api> to obtain a
`client_id` and `client_secret`.

### 1.1 Step 1 — Request authorization

Redirect the user to the authorization page so they can grant access.

- Web: `GET https://www.strava.com/oauth/authorize`
- Android: `GET https://www.strava.com/oauth/mobile/authorize`
- iOS: custom URL scheme via `ASWebAuthenticationSession`

Query parameters:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `client_id` | yes | Your application's ID. |
| `redirect_uri` | yes | URL to redirect to after authorization. Must match the callback domain set in app settings. `localhost`/`127.0.0.1` are whitelisted for development. |
| `response_type` | yes | Must be `code`. |
| `scope` | yes | Comma-separated list of [scopes](#2-scopes). |
| `approval_prompt` | no | `force` (always show the prompt) or `auto` (default). |
| `state` | no | Returned unchanged in the redirect; use for CSRF protection / app state. |

On approval Strava redirects to `redirect_uri?state=...&code=<code>&scope=<granted_scopes>`.
**Always check the granted `scope`** — the user may have unchecked some.
If the user denies, the redirect contains `error=access_denied`.

### 1.2 Step 2 — Token exchange

Exchange the authorization `code` for tokens.

```
POST https://www.strava.com/oauth/token
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `client_id` | yes | Application ID. |
| `client_secret` | yes | Application secret. |
| `code` | yes | The authorization code from step 1. |
| `grant_type` | yes | Must be `authorization_code`. |

Response:

```json
{
  "token_type": "Bearer",
  "expires_at": 1568775134,
  "expires_in": 21600,
  "refresh_token": "e5n567567...",
  "access_token": "a4b945687g...",
  "athlete": { /* SummaryAthlete */ }
}
```

- `access_token` — short-lived (≈6 hours). Use in the `Authorization` header.
- `refresh_token` — long-lived. Store securely; used to mint new access tokens.
- `expires_at` — Unix epoch (seconds) when the access token expires.
- `expires_in` — seconds until expiry.

> Note: within the OpenAPI spec the OAuth endpoints are declared under the API
> base path (`https://www.strava.com/api/v3/oauth/authorize` and
> `.../oauth/token`). In practice the documented and widely used host is
> `https://www.strava.com/oauth/...`. Both resolve.

### 1.3 Step 3 — Refresh the access token

When `expires_at` has passed (or is near), exchange the refresh token:

```
POST https://www.strava.com/oauth/token
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `client_id` | yes | Application ID. |
| `client_secret` | yes | Application secret. |
| `grant_type` | yes | Must be `refresh_token`. |
| `refresh_token` | yes | The stored refresh token. |

Response contains a new `access_token`, `expires_at`, `expires_in`, and
possibly a new `refresh_token` (always persist the returned refresh token).
Older and newer access tokens both work until their expiry.

### 1.4 Deauthorization / revoke

Invalidates all tokens and removes the app from the user's settings.

- Recommended: `POST https://www.strava.com/oauth/revoke` (HTTP Basic auth with
  client credentials).
- Legacy: `POST https://www.strava.com/oauth/deauthorize` with `access_token`.

---

## 2. Scopes

Request the minimum scopes you need; comma-separate multiple scopes.

| Scope | Grants |
|-------|--------|
| `read` | Read public segments, public routes, public profile data, public posts, public events, club feeds, and leaderboards. |
| `read_all` | Read private routes, private segments, and private events for the user. |
| `profile:read_all` | Read all profile information even if visibility is set to Followers or Only You. |
| `profile:write` | Update the user's weight and FTP; star/unstar segments on their behalf. |
| `activity:read` | Read activities visible to Everyone and Followers, excluding privacy-zone data. |
| `activity:read_all` | Everything in `activity:read`, plus privacy-zone data and Only-You activities. |
| `activity:write` | Create manual activities and uploads; edit activities visible to the app. |

The per-endpoint required scopes are noted in the [Endpoints](#4-endpoints)
section.

---

## 3. Rate limits

Limits are enforced **per application** in two tiers and two windows:

| Tier | 15-minute window | Daily window |
|------|------------------|--------------|
| Overall (all requests) | 200 | 2,000 |
| Read (non-upload requests) | 100 | 1,000 |

- The 15-minute window resets on the quarter hour (`:00`, `:15`, `:30`, `:45`).
- The daily window resets at midnight UTC.
- Requests counted against the 15-minute limit also count toward the daily limit.
- These are defaults for new apps. Apps can self-upgrade limits (e.g. 400 / 200
  per 15 min for up to ~10 athletes); scaling beyond requires Strava review.

### Response headers

| Header | Meaning |
|--------|---------|
| `X-RateLimit-Limit` | Overall limits as `15min,daily` (e.g. `200,2000`). |
| `X-RateLimit-Usage` | Overall usage as `15min,daily`. |
| `X-ReadRateLimit-Limit` | Read limits as `15min,daily` (e.g. `100,1000`). |
| `X-ReadRateLimit-Usage` | Read usage as `15min,daily`. |

### Exceeding limits

Returns **`429 Too Many Requests`** with a JSON [`Fault`](#7-errors) body.
Back off until the next window reset.

---

## 4. Endpoints

All paths are relative to `https://www.strava.com/api/v3`. Parameters marked
`*` are required. `page` defaults to 1; `per_page` defaults to 30.

### 4.1 Athletes

| Method | Path | Summary | Scope |
|--------|------|---------|-------|
| GET | `/athlete` | Get the currently authenticated athlete. Returns a [`DetailedAthlete`](#detailedathlete). | `profile:read_all` |
| GET | `/athlete/zones` | Get the authenticated athlete's heart-rate and power [`Zones`](#zones). | `profile:read_all` |
| GET | `/athletes/{id}/stats` | Get [`ActivityStats`](#activitystats) for an athlete (only the authenticated athlete's own stats). | `profile:read_all` |
| PUT | `/athlete` | Update the authenticated athlete. | `profile:write` |

**`GET /athletes/{id}/stats`** — `id*` (path), `page`, `per_page` (query).
**`PUT /athlete`** — `weight*` (the new weight in kilograms).

### 4.2 Activities

| Method | Path | Summary | Scope |
|--------|------|---------|-------|
| POST | `/activities` | Create a manual activity. | `activity:write` |
| GET | `/activities/{id}` | Get a [`DetailedActivity`](#detailedactivity) owned by the athlete. | `activity:read` (`activity:read_all` for Only-You) |
| PUT | `/activities/{id}` | Update an activity ([`UpdatableActivity`](#updatableactivity) body). | `activity:write` |
| GET | `/athlete/activities` | List the authenticated athlete's activities ([`SummaryActivity`](#summaryactivity) array). | `activity:read` |
| GET | `/activities/{id}/comments` | List [`Comment`](#comment)s on an activity. | `activity:read` |
| GET | `/activities/{id}/kudos` | List athletes who kudoed an activity ([`SummaryAthlete`](#summaryathlete) array). | `activity:read` |
| GET | `/activities/{id}/laps` | List the [`Lap`](#lap)s of an activity. | `activity:read` |
| GET | `/activities/{id}/zones` | Get the [`ActivityZone`](#activityzone)s of an activity (Summit feature). | `activity:read` |

**`POST /activities`** (form data):
`name*`, `sport_type*`, `start_date_local*` (ISO-8601), `elapsed_time*`
(seconds), `type` (deprecated, prefer `sport_type`), `description`, `distance`
(meters), `trainer` (`0`/`1`), `commute` (`0`/`1`).

**`GET /activities/{id}`** — `id*` (path), `include_all_efforts` (query, bool).

**`PUT /activities/{id}`** — `id*` (path), body = [`UpdatableActivity`](#updatableactivity).

**`GET /athlete/activities`** — `before` (epoch), `after` (epoch), `page`,
`per_page` (all query).

**`GET /activities/{id}/comments`** — `id*` (path); supports both legacy
(`page`, `per_page`) and cursor (`page_size`, `after_cursor`) pagination.

### 4.3 Clubs

| Method | Path | Summary | Scope |
|--------|------|---------|-------|
| GET | `/clubs/{id}` | Get a [`DetailedClub`](#detailedclub). | `read` |
| GET | `/clubs/{id}/activities` | List recent club activities ([`ClubActivity`](#clubactivity) array). | `read` |
| GET | `/clubs/{id}/admins` | List club administrators ([`SummaryAthlete`](#summaryathlete) array). | `read` |
| GET | `/clubs/{id}/members` | List club members ([`ClubAthlete`](#clubathlete) array). | `read` |
| GET | `/athlete/clubs` | List clubs the authenticated athlete belongs to. | `read` |

All take `id*` (path, except `/athlete/clubs`) plus `page` / `per_page` (query).

### 4.4 Gear

| Method | Path | Summary | Scope |
|--------|------|---------|-------|
| GET | `/gear/{id}` | Get a [`DetailedGear`](#detailedgear) item (bike or shoe). | `profile:read_all` |

`id*` (path) — the gear ID string (e.g. `b12345`, `g98765`).

### 4.5 Routes

| Method | Path | Summary | Scope |
|--------|------|---------|-------|
| GET | `/routes/{id}` | Get a [`Route`](#route). | `read` (`read_all` for private) |
| GET | `/routes/{id}/export_gpx` | Export a route as GPX. | `read` |
| GET | `/routes/{id}/export_tcx` | Export a route as TCX. | `read` |
| GET | `/athletes/{id}/routes` | List an athlete's routes ([`Route`](#route) array). | `read` |

`id*` (path); list endpoint also takes `page` / `per_page`.

### 4.6 Segments

| Method | Path | Summary | Scope |
|--------|------|---------|-------|
| GET | `/segments/{id}` | Get a [`DetailedSegment`](#detailedsegment). | `read_all` (private) / `read` |
| GET | `/segments/explore` | Search for popular segments within a bounding box. Returns [`ExplorerResponse`](#explorerresponse). | `read` |
| GET | `/segments/starred` | List segments starred by the authenticated athlete. | `read` |
| PUT | `/segments/{id}/starred` | Star or unstar a segment. | `profile:write` |

**`GET /segments/explore`** (query): `bounds*` (`sw_lat,sw_lng,ne_lat,ne_lng`),
`activity_type` (`running`/`riding`), `min_cat` (0–5), `max_cat` (0–5).

**`PUT /segments/{id}/starred`** — `id*` (path), `starred*` (form, bool).

**`GET /segments/starred`** — `page`, `per_page`.

### 4.7 Segment Efforts

| Method | Path | Summary | Scope |
|--------|------|---------|-------|
| GET | `/segment_efforts` | List the authenticated athlete's efforts on a given segment. | `activity:read_all` |
| GET | `/segment_efforts/{id}` | Get a [`DetailedSegmentEffort`](#detailedsegmenteffort). | `activity:read_all` |

**`GET /segment_efforts`** (query): `segment_id*`, `start_date_local`
(ISO-8601), `end_date_local` (ISO-8601), `per_page`.

### 4.8 Streams

Streams are the raw time-series data of an activity, route, segment, or effort.

| Method | Path | Summary |
|--------|------|---------|
| GET | `/activities/{id}/streams` | Get activity streams ([`StreamSet`](#streamset)). |
| GET | `/segment_efforts/{id}/streams` | Get segment-effort streams. |
| GET | `/segments/{id}/streams` | Get segment streams. |
| GET | `/routes/{id}/streams` | Get route streams. |

For activity/effort/segment streams (query):

| Parameter | Required | Description |
|-----------|----------|-------------|
| `id` | yes (path) | Object identifier. |
| `keys` | yes | Comma-separated [stream types](#stream-types) to return. |
| `key_by_type` | yes | Must be `true` — returns the response keyed by stream type. |

Scope: `activity:read` (activity streams). Route streams take only `id`.

**Stream types** (`keys`): `time`, `distance`, `latlng`, `altitude`,
`velocity_smooth`, `heartrate`, `cadence`, `watts`, `temp`, `moving`,
`grade_smooth`.

### 4.9 Uploads

| Method | Path | Summary | Scope |
|--------|------|---------|-------|
| POST | `/uploads` | Upload an activity file (FIT, TCX, or GPX, optionally gzipped). | `activity:write` |
| GET | `/uploads/{uploadId}` | Poll the status of an upload ([`Upload`](#upload)). | `activity:write` |

**`POST /uploads`** (multipart form data):

| Field | Description |
|-------|-------------|
| `file` | The activity file. |
| `data_type` | One of `fit`, `fit.gz`, `tcx`, `tcx.gz`, `gpx`, `gpx.gz`. |
| `name` | Activity name. |
| `description` | Activity description. |
| `trainer` | `1` to mark as a trainer activity. |
| `commute` | `1` to mark as a commute. |
| `external_id` | Your unique identifier for the upload. |

Uploads are processed asynchronously. Poll `GET /uploads/{uploadId}` until
`activity_id` is populated (success) or `error` is set (failure).

---

## 5. Webhook Events API

Webhooks push events to your server in near real-time instead of polling.
Events fire when an activity is created, updated, or deleted, or when an athlete
deauthorizes your application.

Base: `https://www.strava.com/api/v3/push_subscriptions`

### 5.1 Create a subscription

```
POST https://www.strava.com/api/v3/push_subscriptions
```

| Field | Required | Description |
|-------|----------|-------------|
| `client_id` | yes | Application ID. |
| `client_secret` | yes | Application secret. |
| `callback_url` | yes | Your HTTPS endpoint (≤255 chars). |
| `verify_token` | yes | An arbitrary string you choose; echoed back during validation. |

### 5.2 Validation handshake

Immediately after the POST, Strava sends a **GET** to your `callback_url`:

```
GET {callback_url}?hub.mode=subscribe&hub.challenge=<random>&hub.verify_token=<your token>
```

Your endpoint must verify `hub.verify_token` and respond within **2 seconds**
with HTTP 200 and JSON echoing the challenge:

```json
{ "hub.challenge": "<random>" }
```

If validation succeeds, the original POST returns the subscription `id`.

### 5.3 Event payload

Strava POSTs an event to your `callback_url`:

```json
{
  "object_type": "activity",
  "aspect_type": "update",
  "object_id": 1360128428,
  "owner_id": 134815,
  "subscription_id": 120475,
  "event_time": 1516126040,
  "updates": { "title": "Messy" }
}
```

| Field | Description |
|-------|-------------|
| `object_type` | `activity` or `athlete`. |
| `aspect_type` | `create`, `update`, or `delete`. |
| `object_id` | Activity ID or athlete ID. |
| `owner_id` | Athlete owning the object. |
| `subscription_id` | Push subscription ID. |
| `event_time` | Unix timestamp. |
| `updates` | Changed fields. For activities: `title`, `type`, `private`. For athlete deauth: `{"authorized":"false"}`. |

Acknowledge every event with **HTTP 200 within 2 seconds**, otherwise Strava
retries (up to ~3 times). One subscription is allowed per application.

### 5.4 View / delete subscriptions

- **View:** `GET /push_subscriptions?client_id=...&client_secret=...`
- **Delete:** `DELETE /push_subscriptions/{id}?client_id=...&client_secret=...`
  → returns `204 No Content`.

---

## 6. Data models

Field types use OpenAPI conventions (`integer`, `number`, `string`,
`boolean`, `array<T>`). Detailed types extend their summary/meta counterparts
via `allOf` — the field lists below are the fully merged set.

### Activity models

#### MetaActivity
- `id` (int64)

#### SummaryActivity
Extends `MetaActivity`. Fields: `external_id`, `upload_id` (int64), `athlete`
([MetaAthlete](#meta-objects)), `name`, `distance` (float, meters),
`moving_time` (s), `elapsed_time` (s), `total_elevation_gain` (float, m),
`elev_high`, `elev_low`, `type` ([ActivityType](#enumerations), deprecated),
`sport_type` ([SportType](#enumerations)), `start_date` (date-time),
`start_date_local` (date-time), `timezone`, `start_latlng` ([LatLng](#latlng)),
`end_latlng`, `achievement_count`, `kudos_count`, `comment_count`,
`athlete_count`, `photo_count`, `total_photo_count`, `map`
([PolylineMap](#polylinemap)), `device_name`, `trainer` (bool), `commute`
(bool), `manual` (bool), `private` (bool), `flagged` (bool), `workout_type`,
`upload_id_str`, `average_speed` (m/s), `max_speed` (m/s), `has_kudoed` (bool),
`hide_from_home` (bool), `gear_id`, `kilojoules`, `average_watts`,
`device_watts` (bool), `max_watts`, `weighted_average_watts`.

#### DetailedActivity
Extends `SummaryActivity`, adds: `description`, `photos`
([PhotosSummary](#photossummary)), `gear` ([SummaryGear](#gear-models)),
`calories` (float), `segment_efforts` (array&lt;[DetailedSegmentEffort](#detailedsegmenteffort)&gt;),
`device_name`, `embed_token`, `splits_metric` (array&lt;[Split](#split)&gt;),
`splits_standard` (array&lt;Split&gt;), `laps` (array&lt;[Lap](#lap)&gt;),
`best_efforts` (array&lt;DetailedSegmentEffort&gt;).

#### UpdatableActivity
The PUT `/activities/{id}` body: `commute` (bool), `trainer` (bool),
`hide_from_home` (bool), `description`, `name`, `type` (ActivityType),
`sport_type` (SportType), `gear_id`.

#### ClubActivity
`athlete` (MetaAthlete with first name + last initial only), `name`, `distance`,
`moving_time`, `elapsed_time`, `total_elevation_gain`, `type`, `sport_type`,
`workout_type`.

### Athlete models

#### Meta objects
- **MetaAthlete** — `id` (int64).

#### SummaryAthlete
Extends `MetaAthlete`. Fields: `resource_state`, `firstname`, `lastname`,
`profile_medium` (URL), `profile` (URL), `city`, `state`, `country`, `sex`,
`premium` (bool), `summit` (bool), `created_at` (date-time), `updated_at`
(date-time).

#### DetailedAthlete
Extends `SummaryAthlete`, adds: `follower_count`, `friend_count`,
`measurement_preference` (`feet`/`meters`), `ftp`, `weight` (float, kg),
`clubs` (array&lt;[SummaryClub](#club-models)&gt;), `bikes`
(array&lt;[SummaryGear](#gear-models)&gt;), `shoes` (array&lt;SummaryGear&gt;).

#### ClubAthlete
`resource_state`, `firstname`, `lastname` (last initial), `member` (status
string), `admin` (bool), `owner` (bool).

#### ActivityStats
Rolled-up totals for an athlete: `biggest_ride_distance` (double),
`biggest_climb_elevation_gain` (double), and `recent_*`, `ytd_*`, `all_*`
totals for `ride`/`run`/`swim`, each an **ActivityTotal**.

**ActivityTotal** — `count`, `distance` (float), `moving_time` (s),
`elapsed_time` (s), `elevation_gain` (float), `achievement_count`.

#### Zones
- **Zones** — `heart_rate` (HeartRateZoneRanges), `power` (PowerZoneRanges).
- **HeartRateZoneRanges** — `custom_zones` (bool), `zones` (ZoneRanges).
- **PowerZoneRanges** — `zones` (ZoneRanges).
- **ZoneRanges** — array of **ZoneRange** (`min`, `max` integers).
- **ActivityZone** — `score`, `distribution_buckets`
  (TimedZoneDistribution), `type` (`heartrate`/`power`), `sensor_based` (bool),
  `points`, `custom_zones` (bool), `max`.
- **TimedZoneDistribution** — array of **TimedZoneRange** (`min`, `max`, `time`).

### Club models

#### MetaClub
`id` (int64), `resource_state`, `name`.

#### SummaryClub
Extends `MetaClub`, adds: `profile_medium`, `cover_photo`, `cover_photo_small`,
`sport_type` (`cycling`/`running`/`triathlon`/`other`), `activity_types`
(array&lt;ActivityType&gt;), `city`, `state`, `country`, `private` (bool),
`member_count`, `featured` (bool), `verified` (bool), `url`.

#### DetailedClub
Extends `SummaryClub`, adds: `membership` (`member`/`pending`), `admin` (bool),
`owner` (bool), `following_count`.

Also: **ClubAnnouncement** (`id`, `club_id`, `athlete`, `created_at`, `message`)
and **MembershipApplication** (`success`, `active`, `membership`).

### Gear models

#### SummaryGear
`id` (string), `resource_state`, `primary` (bool), `name`, `distance` (float, m).

#### DetailedGear
Extends `SummaryGear`, adds: `brand_name`, `model_name`, `frame_type` (int),
`description`.

### Segment models

#### SummarySegment
`id` (int64), `name`, `activity_type` (`Ride`/`Run`), `distance` (float),
`average_grade` (float, %), `maximum_grade` (float, %), `elevation_high`,
`elevation_low`, `start_latlng` ([LatLng](#latlng)), `end_latlng`,
`climb_category` (0–5), `city`, `state`, `country`, `private` (bool),
`athlete_pr_effort` (SummaryPRSegmentEffort), `athlete_segment_stats`
(SummarySegmentEffort).

#### DetailedSegment
Extends `SummarySegment`, adds: `created_at`, `updated_at`,
`total_elevation_gain` (float), `map` ([PolylineMap](#polylinemap)),
`effort_count`, `athlete_count`, `hazardous` (bool), `star_count`.

#### ExplorerResponse / ExplorerSegment
- **ExplorerResponse** — `segments` (array&lt;ExplorerSegment&gt;).
- **ExplorerSegment** — `id`, `name`, `climb_category`, `climb_category_desc`,
  `avg_grade`, `start_latlng`, `end_latlng`, `elev_difference`, `distance`,
  `points` (encoded polyline).

### Segment effort models

#### SummarySegmentEffort
`id` (int64), `activity_id` (int64), `elapsed_time` (s), `start_date`,
`start_date_local`, `distance` (float), `is_kom` (bool).

#### DetailedSegmentEffort
Extends `SummarySegmentEffort`, adds: `name`, `activity` (MetaActivity),
`athlete` (MetaAthlete), `moving_time` (s), `start_index`, `end_index`,
`average_cadence`, `average_watts`, `device_watts` (bool), `average_heartrate`,
`max_heartrate`, `segment` (SummarySegment), `kom_rank` (1–10 or null),
`pr_rank` (1–3 or null), `hidden` (bool).

#### SummaryPRSegmentEffort
`pr_activity_id`, `pr_elapsed_time`, `pr_date`, `effort_count`.

### Route

**Route** — `athlete` (SummaryAthlete), `description`, `distance` (float),
`elevation_gain` (float), `id` (int64), `id_str`, `map`
([PolylineMap](#polylinemap)), `name`, `private` (bool), `starred` (bool),
`timestamp`, `type` (1=ride, 2=run), `sub_type` (1=road, 2=MTB, 3=CX, 4=trail,
5=mixed), `created_at`, `updated_at`, `estimated_moving_time` (s), `segments`
(array&lt;SummarySegment&gt;), `waypoints` (array&lt;[Waypoint](#waypoint)&gt;).

### Lap

**Lap** — `id` (int64), `activity` (MetaActivity), `athlete` (MetaAthlete),
`average_cadence`, `average_speed`, `distance`, `elapsed_time`, `start_index`,
`end_index`, `lap_index`, `max_speed`, `moving_time`, `name`, `pace_zone`,
`split`, `start_date`, `start_date_local`, `total_elevation_gain`.

### Comment

**Comment** — `id` (int64), `activity_id` (int64), `text`, `athlete`
(SummaryAthlete), `created_at`.

### Upload

**Upload** — `id` (int64), `id_str`, `external_id`, `error` (string or null),
`status` (human-readable processing status), `activity_id` (int64, null until
processed).

### Stream models

#### StreamSet
A container keyed by stream type, returned when `key_by_type=true`. Keys:
`time`, `distance`, `latlng`, `altitude`, `velocity_smooth`, `heartrate`,
`cadence`, `watts`, `temp`, `moving`, `grade_smooth`.

#### BaseStream
Every stream extends `BaseStream`: `original_size` (int), `resolution`
(`low`/`medium`/`high`), `series_type` (`distance`/`time`).

| Stream | `data` element type |
|--------|---------------------|
| `TimeStream` | integer (seconds from start) |
| `DistanceStream` | number (meters) |
| `LatLngStream` | [LatLng](#latlng) (`[lat, lng]`) |
| `AltitudeStream` | number (meters) |
| `SmoothVelocityStream` | number (m/s) |
| `HeartrateStream` | integer (bpm) |
| `CadenceStream` | integer (rpm) |
| `PowerStream` | integer (watts) |
| `TemperatureStream` | integer (°C) |
| `MovingStream` | boolean |
| `SmoothGradeStream` | number (%) |

### Shared / utility types

#### LatLng
A two-element array `[latitude, longitude]` of floats.

#### PolylineMap
`id`, `polyline` (encoded, detailed), `summary_polyline` (encoded, simplified).

#### Split
`distance`, `elapsed_time`, `elevation_difference`, `moving_time`, `split`,
`average_speed`, `average_grade_adjusted_speed`, `average_heartrate`,
`pace_zone`.

#### Waypoint
`latlng` (LatLng), `target_latlng`, `categories` (array&lt;string&gt;),
`title`, `description`, `distance_into_route`.

#### PhotosSummary
`count`, `primary` (`id`, `source`, `unique_id`, `urls` map).

### Enumerations

- **SportType** — `AlpineSki`, `BackcountrySki`, `Badminton`, `Canoeing`,
  `Crossfit`, `EBikeRide`, `Elliptical`, `EMountainBikeRide`, `Golf`,
  `GravelRide`, `Handcycle`, `HighIntensityIntervalTraining`, `Hike`,
  `IceSkate`, `InlineSkate`, `Kayaking`, `Kitesurf`, `MountainBikeRide`,
  `NordicSki`, `Pickleball`, `Pilates`, `Racquetball`, `Ride`, `RockClimbing`,
  `RollerSki`, `Rowing`, `Run`, `Sail`, `Skateboard`, `Snowboard`, `Snowshoe`,
  `Soccer`, `Squash`, `StairStepper`, `StandUpPaddling`, `Surfing`, `Swim`,
  `TableTennis`, `Tennis`, `TrailRun`, `Velomobile`, `VirtualRide`,
  `VirtualRow`, `VirtualRun`, `Walk`, `WeightTraining`, `Wheelchair`,
  `Windsurf`, `Workout`, `Yoga`.
- **ActivityType** *(deprecated — use `SportType`)* — the legacy subset such as
  `Ride`, `Run`, `Swim`, `Hike`, `Walk`, `AlpineSki`, etc.

---

## 7. Errors

Errors are returned as a **Fault** object with the appropriate HTTP status code.

```json
{
  "message": "Authorization Error",
  "errors": [
    { "resource": "Athlete", "field": "access_token", "code": "invalid" }
  ]
}
```

- **Fault** — `message` (string), `errors` (array&lt;Error&gt;).
- **Error** — `code` (string), `field` (string), `resource` (string).

Common status codes:

| Status | Meaning |
|--------|---------|
| 200 / 201 | Success. |
| 204 | Success, no content (e.g. webhook delete). |
| 400 | Bad request (validation / missing parameters). |
| 401 | Unauthorized (missing, expired, or invalid access token). |
| 403 | Forbidden (insufficient scope, or app at athlete capacity). |
| 404 | Resource not found. |
| 429 | Rate limit exceeded. |
| 500 | Server error. |

---

## 8. The OpenAPI specification files

The machine-readable spec is stored under [`strava-api-spec/swagger/`](./strava-api-spec/swagger/):

```
strava-api-spec/swagger/
├── swagger.json          # main spec: info, paths, security, parameters (32 operations)
├── activity.json         # DetailedActivity, SummaryActivity, MetaActivity, UpdatableActivity, ClubActivity
├── activity_stats.json   # ActivityStats
├── athlete.json          # DetailedAthlete, SummaryAthlete, ClubAthlete, MetaAthlete
├── club.json             # DetailedClub, SummaryClub, MetaClub, ClubAnnouncement, MembershipApplication
├── comment.json          # Comment
├── fault.json            # Fault, Error
├── gear.json             # DetailedGear, SummaryGear
├── lap.json              # Lap
├── route.json            # Route
├── segment.json          # DetailedSegment, SummarySegment, ExplorerResponse, ExplorerSegment
├── segment_effort.json   # DetailedSegmentEffort, SummarySegmentEffort, SummaryPRSegmentEffort
├── stream.json           # BaseStream + all stream types + StreamSet
├── upload.json           # Upload
└── zones.json            # Zones, HeartRateZoneRanges, PowerZoneRanges, ActivityZone, ...
```

`swagger.json` references the model files via absolute `$ref` URLs of the form
`https://developers.strava.com/swagger/<file>.json#/<Model>`. To resolve them
fully offline, rewrite those `$ref`s to the local relative paths
(`<file>.json#/<Model>`) or use a `$ref` resolver that maps the
`https://developers.strava.com/swagger/` prefix to this directory.

These files were retrieved on 2026-06-02 from
`https://developers.strava.com/swagger/`.
