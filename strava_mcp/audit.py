"""Structured, append-only audit trail (JSONL) — a sink separate from the human log.

One JSON object per line is written to ``./.logs/audit.log`` (rotating), carrying
three streams (``mcp``, ``strava``, ``dashboard``) with a request + response event
each, correlated by ``req_id`` (research R1/R2/R4, contracts/audit-events.md).

The sink reuses the human log's secret redaction and is **best-effort**: a sink
failure never breaks the observed operation (FR-016).
"""

from __future__ import annotations

import contextvars
import json
import logging
import secrets
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from strava_mcp.logging import RedactionFilter, scrub

_AUDIT_LOGGER = "strava_mcp.audit"

# Current logical-operation id; thread/async-local, no cross-thread bleed (research R4).
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "strava_audit_req_id", default=None
)


def setup_audit(audit_path: Path | str) -> logging.Logger:
    """Configure the ``strava_mcp.audit`` JSONL logger.

    One ``RotatingFileHandler`` (2MB×3) with a JSON-only formatter and the shared
    ``RedactionFilter`` attached; ``propagate=False`` so audit lines never reach the
    human log. Idempotent and creates the parent directory if missing.
    """
    logger = logging.getLogger(_AUDIT_LOGGER)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Idempotent: only our own rotating-file handler counts (a foreign handler,
    # e.g. pytest's log capture, must not suppress the real sink).
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return logger

    audit_file = Path(audit_path)
    audit_file.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        audit_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    # JSON-only: each line is the pre-serialized JSON message, nothing else.
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(RedactionFilter())
    logger.addHandler(handler)
    return logger


def emit(stream: str, event: str, *, req_id: str | None = None, **fields: object) -> None:
    """Serialize ``{ts, stream, event, req_id, **fields}`` as one JSON line and write it.

    Best-effort: ANY exception (serialization, IO) is caught and ignored — never
    propagates to the caller (FR-016). ``req_id`` defaults to the current correlation
    id. ``ts`` is UTC ISO-8601; values serialized with ``default=str`` so emit is total.
    """
    try:
        record = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stream": stream,
            "event": event,
            "req_id": req_id or current_req_id(),
            **fields,
        }
        line = json.dumps(record, separators=(",", ":"), default=str)
        logging.getLogger(_AUDIT_LOGGER).info(line)
    except Exception:  # noqa: BLE001 - best-effort sink, never breaks the caller
        pass


@contextmanager
def correlation_scope() -> Iterator[str]:
    """Set a fresh 8-hex correlation id for the duration of the block; reset on exit.

    Thread/async-local (contextvars) — no cross-thread bleed.
    """
    req_id = secrets.token_hex(4)
    token = _correlation_id.set(req_id)
    try:
        yield req_id
    finally:
        _correlation_id.reset(token)


def current_req_id() -> str:
    """Active correlation id, or a fresh ephemeral id if none is set.

    A fresh id keeps an un-scoped call attributable (its request/response still
    correlate with each other within the same ``emit`` pair if passed explicitly).
    """
    return _correlation_id.get() or secrets.token_hex(4)


def summarize_args(mapping: Mapping[str, object]) -> dict[str, object]:
    """Sanitized argument summary: scalars kept, collections summarized, strings scrubbed.

    Never a verbatim dump of nested structures (data-model.md "Sanitized").
    """
    return {key: _summarize_value(value) for key, value in mapping.items()}


def _summarize_value(value: object) -> object:
    if isinstance(value, str):
        return scrub(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {"keys": sorted(str(k) for k in value), "size": len(value)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return {"size": len(value)}
    return scrub(str(value))
