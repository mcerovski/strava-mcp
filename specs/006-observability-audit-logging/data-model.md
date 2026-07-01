# Phase 1 Data Model: Observability & Audit Logging

This feature introduces **no database schema**. Its "data" is the on-disk log/audit records and the
in-process correlation context. Two sinks, one in-memory entity.

## Entity: Audit Event (a line in `./.logs/audit.log`)

One JSON object per line. **Mandatory fields on every event** (FR-014):

| Field    | Type   | Notes |
|----------|--------|-------|
| `ts`     | string | UTC ISO-8601, e.g. `2026-06-25T14:03:12Z` (second precision is sufficient). |
| `stream` | string | One of `mcp` \| `strava` \| `dashboard`. |
| `event`  | string | `request` \| `response` \| `interaction`. |
| `req_id` | string | Correlation id (8 hex chars) grouping events of one logical operation. |

Stream-specific fields are added alongside the mandatory four. All string values pass through
redaction before the line is written (FR-015).

### Stream `mcp` (agent/MCP tool calls)

`event: "request"`
| Field  | Type   | Notes |
|--------|--------|-------|
| `tool` | string | Tool name, e.g. `get_activity`. |
| `args` | object | **Sanitized** argument summary: scalars kept, collections summarized to size/keys, redacted. Never a verbatim dump. |

`event: "response"`
| Field    | Type    | Notes |
|----------|---------|-------|
| `tool`   | string  | Same tool name. |
| `status` | string  | `ok` \| `error`. |
| `ms`     | number  | Duration in milliseconds. |
| `error`  | string? | Present only on `error`: exception class + redacted message. |

### Stream `strava` (worker → Strava API)

`event: "request"`
| Field    | Type    | Notes |
|----------|---------|-------|
| `method` | string  | `GET` (read-only client). |
| `path`   | string  | Request path, e.g. `/athlete/activities`. |
| `query`  | object? | Sanitized query-param summary (e.g. `per_page`, `before`); no secrets. |

`event: "response"`
| Field        | Type    | Notes |
|--------------|---------|-------|
| `method`     | string  | `GET`. |
| `path`       | string  | Request path. |
| `status`     | number? | HTTP status; absent when a transport error occurred. |
| `ms`         | number  | Latency in milliseconds. |
| `rate_limit` | object? | `RateLimitBudget.snapshot()` shape: `read_15min`, `read_daily`, `overall_15min`, `overall_daily`, `self_limit`. Present when a limiter is attached. |
| `error`      | string? | Present on transport failure or mapped fault: class + redacted Strava fault message. |

### Stream `dashboard` (user interactions)

`event: "interaction"`
| Field    | Type    | Notes |
|----------|---------|-------|
| `method` | string  | `GET` \| `HEAD`. |
| `path`   | string  | Request path, e.g. `/activity/123`. |
| `query`  | object? | Sanitized query summary (e.g. `sport_type`, `page`). |
| `status` | number  | Response HTTP status (200/404/500…). |
| `ms`     | number  | Latency in milliseconds. |
| `client` | string  | Client address string (loopback). |

### Example lines

```json
{"ts":"2026-06-25T14:03:12Z","stream":"mcp","event":"request","req_id":"7c2d11a8","tool":"get_activity","args":{"id":123}}
{"ts":"2026-06-25T14:03:12Z","stream":"mcp","event":"response","req_id":"7c2d11a8","tool":"get_activity","status":"ok","ms":3}
{"ts":"2026-06-25T14:07:40Z","stream":"strava","event":"request","req_id":"9f3a1c20","method":"GET","path":"/activities/456"}
{"ts":"2026-06-25T14:07:40Z","stream":"strava","event":"response","req_id":"9f3a1c20","method":"GET","path":"/activities/456","status":200,"ms":214,"rate_limit":{"read_15min":{"used":42,"limit":100},"read_daily":{"used":310,"limit":1000},"overall_15min":null,"overall_daily":null,"self_limit":900}}
{"ts":"2026-06-25T14:07:41Z","stream":"strava","event":"request","req_id":"9f3a1c20","method":"GET","path":"/activities/456/streams"}
{"ts":"2026-06-25T14:07:41Z","stream":"strava","event":"response","req_id":"9f3a1c20","method":"GET","path":"/activities/456/streams","status":200,"ms":120,"rate_limit":{"read_15min":{"used":43,"limit":100},"read_daily":{"used":311,"limit":1000},"overall_15min":null,"overall_daily":null,"self_limit":900}}
{"ts":"2026-06-25T14:05:01Z","stream":"dashboard","event":"interaction","req_id":"1b77ee04","method":"GET","path":"/activity/123","query":{},"status":200,"ms":8,"client":"127.0.0.1"}
```

The four `strava` lines for activity 456 share `req_id` `9f3a1c20`: every Strava call made while
enriching one activity is grouped (FR-008, SC-006). The `mcp` `get_activity` call groups its own
request/response under a separate id and issues **no** Strava call (tools are pure DB readers). The
dashboard interaction has its own id.

## Entity: Correlation context (in-memory)

| Element             | Type                          | Notes |
|---------------------|-------------------------------|-------|
| `_correlation_id`   | `ContextVar[str \| None]`     | Current logical-operation id; thread/async-local, no cross-thread bleed. |
| `correlation_scope()` | context manager             | Sets a fresh `token_hex(4)` on enter, resets on exit. Opened per MCP tool call, per dashboard request, and per worker logical unit (e.g. enriching one activity). |
| `current_req_id()`  | `() -> str`                   | Returns the active id, or a fresh ephemeral id if none is set (so an un-scoped Strava call is still attributable). |

## Sink configuration (derived from `Settings`)

| Setting             | Env                | Default                 | Used by |
|---------------------|--------------------|-------------------------|---------|
| `strava_log_path`   | `STRAVA_LOG_PATH`* | `./.logs/strava-mcp.log` | Human-readable log (existing). |
| `strava_audit_path` | `STRAVA_AUDIT_PATH`| `./.logs/audit.log`     | Structured audit sink (new). |
| `strava_log_level`  | `STRAVA_LOG_LEVEL` | `INFO`                  | Level of the `strava_mcp` human logger (new). |

\* `strava_log_path` already exists in `Settings`. Rotation for both sinks: `maxBytes=2_000_000`,
`backupCount=3` (matches the existing main-log handler).

## Validation rules

- Every emitted audit line MUST parse as JSON and contain `ts`, `stream`, `event`, `req_id` (SC-005).
- `stream ∈ {mcp, strava, dashboard}`; `event ∈ {request, response, interaction}`.
- No field value may contain a secret after redaction (SC-003).
- `emit()` never raises; a serialization/IO error is swallowed (FR-016, SC-004).
- An invalid `STRAVA_LOG_LEVEL` falls back to `INFO` and logs a single warning (no crash).
