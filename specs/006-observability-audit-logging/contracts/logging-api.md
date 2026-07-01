# Contract: Internal Logging & Audit API

The internal surface other modules use to log and audit. Kept small and stable so instrumentation
points stay thin and consistent.

## `strava_mcp/logging.py` (extended)

```python
def setup_logging(log_path: Path | str, *, level: int | str = "INFO") -> logging.Logger:
    """Configure the human-readable `strava_mcp` logger (stdout + rotating file).

    `level` accepts a name ("DEBUG"/"INFO"/...) or an int; an unknown name falls back
    to INFO and logs one warning. Idempotent (repeated calls do not stack handlers).
    """

def scrub(text: str) -> str:
    """Redact token/secret-shaped substrings. Single source of truth, reused by the
    audit sink. (Promoted from the private `_scrub`.)"""

class RedactionFilter(logging.Filter):
    """Existing filter; now also attached to the audit handler."""

def get_logger(name: str = "strava_mcp") -> logging.Logger: ...
```

- Patterns unchanged: bearer headers, `access_token`/`refresh_token`/`client_secret`/`code` JSON
  fields, long hex blobs. `REDACTED = "[REDACTED]"`.

## `strava_mcp/audit.py` (new)

```python
def setup_audit(audit_path: Path | str) -> logging.Logger:
    """Configure the `strava_mcp.audit` JSONL logger: one RotatingFileHandler,
    JSON-only formatter, RedactionFilter attached, propagate=False. Idempotent."""

def emit(stream: str, event: str, *, req_id: str | None = None, **fields: object) -> None:
    """Serialize {ts, stream, event, req_id, **fields} as one JSON line and write it.

    Best-effort: ANY exception (serialization, IO) is caught and ignored — never
    propagates to the caller. `req_id` defaults to the current correlation id.
    `ts` is UTC ISO-8601. Values serialized with default=str so emit is total."""

@contextmanager
def correlation_scope() -> Iterator[str]:
    """Set a fresh 8-hex correlation id for the duration of the block; reset on exit.
    Thread/async-local (contextvars) — no cross-thread bleed."""

def current_req_id() -> str:
    """Active correlation id, or a fresh ephemeral id if none is set."""
```

### Contract guarantees

- `emit()` **never raises** (FR-016). A caller may invoke it without a try/except.
- `setup_audit()` is idempotent and creates the parent directory if missing.
- The audit logger does not propagate to the root or to `strava_mcp` (no double-logging).
- Redaction applies to the final serialized line (catch-all) — callers should still pass sanitized
  field summaries, not verbatim secrets.

## Configuration surface (`strava_mcp/config.py`)

| Setting | Env var | Default | Meaning |
|---------|---------|---------|---------|
| `strava_log_level` | `STRAVA_LOG_LEVEL` | `"INFO"` | Human logger level (name). |
| `strava_audit_path` | `STRAVA_AUDIT_PATH` | `"./.logs/audit.log"` | Structured audit sink path. |

(`strava_log_path` / `STRAVA_LOG_PATH` already exists.)

## Instrumentation expectations (per layer)

| Layer | Human log | Audit emit |
|-------|-----------|------------|
| `client/http.py::StravaClient._request` | DEBUG request; INFO response (`GET path -> 200 (214ms)`); WARNING 4xx / ERROR 5xx+transport with fault message; **no token/headers** | `strava` request + response (+ `rate_limit` snapshot) |
| `mcp/server.py` tool wrapper | INFO ok (`tool ok (Nms)`); ERROR on exception | `mcp` request + response; opens `correlation_scope()` |
| `dashboard/server.py` request | INFO (`GET /path -> 200 (Nms) 127.0.0.1`) | `dashboard` interaction; opens `correlation_scope()` |
| `sync/orchestrator.py::_run_with_cooldown` | `log.exception` on swallowed non-rate-limit failure | (worker Strava calls already audited via the client) |
| `serve` / `dashboard` startup | INFO one-line config summary (host/port, db, log, audit, level) | — |

## Backward compatibility

- The human log format (`%(asctime)s %(levelname)s %(name)s: %(message)s`) is unchanged; existing
  log consumers keep working. New lines are additive.
- No public MCP tool signature or return shape changes (Constitution III).
