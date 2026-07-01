# Contract: Audit Event Stream (`./.logs/audit.log`)

The audit trail is the externally-observable interface of this feature for an operator or a later
review tool. This contract fixes its format so consumers can rely on it.

## File format

- **Encoding**: UTF-8.
- **Framing**: newline-delimited JSON — exactly one JSON object per line, terminated by `\n`. Each
  line is independently parseable (no multi-line records, no trailing comma, no surrounding array).
- **Location**: `STRAVA_AUDIT_PATH` (default `./.logs/audit.log`).
- **Rotation**: size-bounded (`maxBytes=2_000_000`, `backupCount=3`); rotated segments
  (`audit.log.1` … `audit.log.3`) hold valid standalone lines.
- **Ordering**: append-only; lines are written in emission order. Concurrent writers do not interleave
  within a line (the handler serializes writes).

## Mandatory fields (every line)

```
ts      : string  UTC ISO-8601 (e.g. "2026-06-25T14:03:12Z")
stream  : string  "mcp" | "strava" | "dashboard"
event   : string  "request" | "response" | "interaction"
req_id  : string  8 hex chars — correlation id
```

## Per-stream payloads

See [`../data-model.md`](../data-model.md#entity-audit-event-a-line-in-logsauditlog) for the full
field tables. Summary:

| stream | events | key extra fields |
|--------|--------|------------------|
| `mcp` | `request`, `response` | `tool`, `args` (req); `tool`, `status`, `ms`, `error?` (resp) |
| `strava` | `request`, `response` | `method`, `path`, `query?` (req); `status?`, `ms`, `rate_limit?`, `error?` (resp) |
| `dashboard` | `interaction` | `method`, `path`, `query?`, `status`, `ms`, `client` |

## Guarantees (testable)

1. **Completeness** (SC-002): every agent tool call yields one `mcp/request` + one `mcp/response`;
   every Strava call yields one `strava/request` + one `strava/response`; every dashboard request
   yields one `dashboard/interaction`.
2. **Parseability** (SC-005): `json.loads(line)` succeeds for every line and yields the four mandatory
   keys.
3. **No secrets** (SC-003): no line contains a bearer token, access/refresh token, client secret, or
   OAuth code — redaction replaces them with `[REDACTED]`.
4. **Correlation** (SC-006): events of one logical operation share `req_id`.
5. **Best-effort** (SC-004): if the sink cannot be written, the observed operation still completes;
   no exception escapes `emit()`.

## Non-guarantees (explicit)

- No global total ordering across streams beyond per-writer append order.
- No exactly-once across a crash mid-write (a partially written final line may be discarded by a
  parser; this is acceptable for an audit log).
- `req_id` correlates only **within a process/thread context**; cross-process correlation is out of
  scope (see research R4).
