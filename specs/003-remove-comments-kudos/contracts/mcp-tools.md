# Contract: MCP Tool Surface Delta

The MCP server exposes read-only tools over the SQLite mirror. This feature **removes two tools**; all others keep their existing contracts unchanged.

## Removed tools

| Tool | Previous contract | After this feature |
|------|-------------------|--------------------|
| `get_comments(id: int)` | Returned the activity's comments list, or `not_yet_synced`/`not_found`. | **Removed.** Not registered; calling it yields FastMCP's standard *unknown tool* error. |
| `get_kudos(id: int)` | Returned the activity's kudos list, or `not_yet_synced`/`not_found`. | **Removed.** Not registered; calling it yields FastMCP's standard *unknown tool* error. |

## Unchanged tools (regression guard)

`get_laps(id)` and `get_activity_zones(id)` continue to use the shared `_facet` helper and return their collections or the documented `not_yet_synced`/`not_found` signals. Activity list/detail tools keep their shapes **except** that returned activity records no longer carry `kudos_count` or `comment_count` fields (see below).

## Activity record field delta

Any tool returning an activity summary/record (via `ActivitiesRepository._summary_view`) **drops** these two fields:

- `kudos_count` — removed
- `comment_count` — removed

All other fields (`id`, `name`, `sport_type`, `start_date(_local)`, `distance`, `moving_time`, `elapsed_time`, `total_elevation_gain`, `average_heartrate`, `average_watts`, `average_speed`, `gear_id`, …) are unchanged.

## Contract tests impacted

- `tests/contract/test_enrichment_tools.py` — remove `get_comments`/`get_kudos` assertions.
- `tests/contract/test_multi_client.py` — `get_comments`/`get_kudos` must **not** be in the registered tool set.
- Add an assertion that the registered tool set contains neither `get_comments` nor `get_kudos`.
