# Quickstart: Validating Observability & Audit Logging

Runnable scenarios that prove the feature end-to-end. All offline/deterministic — no live Strava.

## Prerequisites

```bash
uv sync
```

Settings (optional; defaults shown) in `.env`:

```
STRAVA_LOG_LEVEL=INFO            # DEBUG to see every outbound Strava request
STRAVA_AUDIT_PATH=./.logs/audit.log
```

## Scenario 1 — Automated suite (primary gate)

```bash
uv run pytest        # all green, including the new logging/audit tests
uv run ruff check .
uv run mypy strava_mcp
```

Expect new tests to cover:
- `tests/unit/test_audit.py` — `emit()` writes one parseable JSON line with `ts/stream/event/req_id`;
  rotation; redaction of a token-bearing field; **best-effort** (a broken sink does not raise).
- `tests/unit/test_log_redaction.py` (extended) — a token routed through an audit field is redacted.
- `tests/contract/test_strava_client_logging.py` — a non-2xx Strava response logs WARNING/ERROR with
  method/path/status/fault message and emits a `strava` response audit event; the bearer token never
  appears in either sink.
- `tests/dashboard/test_dashboard_audit.py` — a page load emits exactly one `dashboard` interaction
  event with status + latency.

## Scenario 2 — Failure visibility by eye (Story 1 / SC-001)

Run the server with a database but a deliberately wrong condition and watch the human log:

```bash
uv run strava-mcp serve        # startup line summarizes host/port, db, log, audit, level
tail -f ./.logs/strava-mcp.log
```

Expect, on a Strava failure during sync, a single line naming the operation and cause, e.g.:

```
2026-06-25 14:03:12 WARNING strava_mcp: GET /activities/123 -> 404 (Not Found)
2026-06-25 14:03:12 ERROR strava_mcp: enrichment activity 123 failed; skipping
Traceback (most recent call last):
  ...
```

No bearer token or secret appears anywhere in the file.

Lower the level to see every outbound request:

```bash
STRAVA_LOG_LEVEL=DEBUG uv run strava-mcp serve
# DEBUG strava_mcp: GET /athlete/activities params={'per_page': 30, 'before': ...}
```

## Scenario 3 — Audit trail across the three streams (Story 2 / SC-002, SC-005, SC-006)

With `serve` (and a sync in progress) and `dashboard` both running, exercise each surface, then
inspect the structured audit:

```bash
# dashboard interaction
curl -s http://127.0.0.1:8722/activity/123 >/dev/null

# inspect the audit trail (valid JSONL — one event per line)
tail -n 20 ./.logs/audit.log | python -m json.tool --json-lines 2>/dev/null \
  || tail -n 20 ./.logs/audit.log     # each line is a standalone JSON object

# count events by stream
cut -d'"' -f8 ./.logs/audit.log | sort | uniq -c     # rough by-position peek; or:
python - <<'PY'
import json, collections
c = collections.Counter()
for line in open("./.logs/audit.log"):
    c[json.loads(line)["stream"]] += 1
print(c)   # expect counts for 'mcp', 'strava', 'dashboard'
PY
```

Expect to see, for one agent `get_activity` call, a `mcp` request+response and the `strava`
request+response it triggered **sharing the same `req_id`** (trace a tool call to its Strava work).

## Scenario 4 — Secrets never logged (Story 3 / SC-003)

```bash
grep -Eri 'bearer |access_token|refresh_token|client_secret' ./.logs/ | grep -v '\[REDACTED\]'
# expect: no matches (every secret-shaped value is redacted)
```

## Scenario 5 — Best-effort sink (Story 3 / SC-004)

Point the audit path at an unwritable location and confirm requests still succeed:

```bash
STRAVA_AUDIT_PATH=/proc/nonexistent/audit.log uv run strava-mcp dashboard &
curl -sf http://127.0.0.1:8722/ >/dev/null && echo "request OK despite broken audit sink"
```

Expect `request OK despite broken audit sink` — the failed audit write is swallowed.

## Expected outcomes (acceptance map)

| Scenario | Proves |
|----------|--------|
| 1 | All FRs via the automated suite (CI gate) |
| 2 | FR-001/002/004/005/006/007, SC-001, SC-007 |
| 3 | FR-009–014, SC-002, SC-005, SC-006 |
| 4 | FR-015, SC-003 |
| 5 | FR-016, SC-004 |
