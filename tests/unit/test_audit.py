"""T008 Audit sink: parseable JSONL, correlation scoping, rotation, best-effort.

Closes SC-005/SC-006 (foundational) and FR-014/FR-016. Offline; a real temp file.
T025 [US3] also extends this file: emit swallows errors on bad sinks; wrapped
tool calls and dashboard requests still complete (FR-016, SC-004).
"""

from __future__ import annotations

import json
import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import pytest
from strava_mcp import audit
from strava_mcp.mcp import server

_MANDATORY = ("ts", "stream", "event", "req_id")


@pytest.fixture(autouse=True)
def _reset_audit_logger() -> None:
    """Isolate the shared ``strava_mcp.audit`` logger between tests."""
    logger = logging.getLogger("strava_mcp.audit")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def _read_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_emit_writes_one_parseable_line_with_mandatory_fields(tmp_path: Path) -> None:
    audit.setup_audit(tmp_path / "audit.log")
    audit.emit("mcp", "request", req_id="abcd1234", tool="get_activity", args={"id": 123})

    for handler in logging.getLogger("strava_mcp.audit").handlers:
        handler.flush()

    lines = _read_lines(tmp_path / "audit.log")
    assert len(lines) == 1
    record = json.loads(lines[0])
    for field in _MANDATORY:
        assert field in record
    assert record["stream"] == "mcp"
    assert record["event"] == "request"
    assert record["req_id"] == "abcd1234"
    assert record["tool"] == "get_activity"


def test_emit_defaults_req_id_to_current_scope(tmp_path: Path) -> None:
    audit.setup_audit(tmp_path / "audit.log")
    with audit.correlation_scope() as req_id:
        audit.emit("strava", "request", method="GET", path="/x")
    for handler in logging.getLogger("strava_mcp.audit").handlers:
        handler.flush()
    record = json.loads(_read_lines(tmp_path / "audit.log")[0])
    assert record["req_id"] == req_id


def test_correlation_scope_is_stable_8hex_and_resets() -> None:
    assert audit.current_req_id() != ""  # ephemeral id when unscoped
    with audit.correlation_scope() as req_id:
        assert len(req_id) == 8
        int(req_id, 16)  # valid hex
        # stable for the duration of the block
        assert audit.current_req_id() == req_id
        assert audit.current_req_id() == req_id
    # reset on exit: a fresh ephemeral id, not the scoped one
    assert audit.current_req_id() != req_id


def test_nested_scopes_restore_outer_id() -> None:
    with audit.correlation_scope() as outer:
        with audit.correlation_scope() as inner:
            assert inner != outer
            assert audit.current_req_id() == inner
        assert audit.current_req_id() == outer


def test_concurrent_scopes_do_not_bleed() -> None:
    seen: dict[str, str] = {}
    barrier = threading.Barrier(2)

    def worker(name: str) -> None:
        with audit.correlation_scope() as req_id:
            barrier.wait()  # force overlap while both scopes are open
            seen[name] = (req_id, audit.current_req_id())  # type: ignore[assignment]

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Each thread saw its own id; no cross-thread bleed.
    assert seen["a"][0] == seen["a"][1]
    assert seen["b"][0] == seen["b"][1]
    assert seen["a"][0] != seen["b"][0]


def test_rotation_produces_valid_standalone_lines(tmp_path: Path) -> None:
    # Drive rotation with a small handler so each segment stays cheap to fill.
    audit_file = tmp_path / "audit.log"
    logger = logging.getLogger("strava_mcp.audit")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(audit_file, maxBytes=512, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(audit.RedactionFilter())
    logger.addHandler(handler)

    for i in range(200):
        audit.emit("strava", "response", req_id="deadbeef", path=f"/activities/{i}", status=200)
    handler.flush()

    segments = [audit_file] + [tmp_path / f"audit.log.{n}" for n in (1, 2, 3)]
    found = 0
    for segment in segments:
        if not segment.exists():
            continue
        for line in _read_lines(segment):
            json.loads(line)  # every line is a standalone JSON object
            found += 1
    assert found > 0
    assert (tmp_path / "audit.log.1").exists()  # rotation actually occurred


# --- T025 [US3] Best-effort: emit swallows errors, wrapped calls still complete ---


class _RaisingHandler(logging.Handler):
    """A handler that always raises on emit — simulates a broken sink."""

    def emit(self, record: logging.LogRecord) -> None:
        raise OSError("disk full")


def test_emit_swallows_handler_error_and_does_not_raise() -> None:
    """T025: emit catches any exception from a broken handler (FR-016, SC-004)."""
    logger = logging.getLogger("strava_mcp.audit")
    logger.addHandler(_RaisingHandler())
    try:
        # Must not raise even though the handler fails.
        audit.emit("mcp", "request", tool="get_athlete")
    finally:
        for h in list(logger.handlers):
            if isinstance(h, _RaisingHandler):
                logger.removeHandler(h)


def test_emit_swallows_serialization_error_and_does_not_raise() -> None:
    """T025: emit catches serialization errors; if json.dumps raises, emit is still safe."""
    with patch("strava_mcp.audit.json.dumps", side_effect=ValueError("bad")):
        audit.emit("strava", "response", status=200)  # must not raise


def test_instrumented_tool_still_returns_on_broken_audit_sink() -> None:
    """T025: a broken audit sink does not prevent the tool from returning its result (SC-004)."""

    @server.instrument("get_athlete")
    def get_athlete() -> dict[str, object]:
        return {"id": 1}

    logger = logging.getLogger("strava_mcp.audit")
    logger.addHandler(_RaisingHandler())
    try:
        result = get_athlete()
        assert result == {"id": 1}
    finally:
        for h in list(logger.handlers):
            if isinstance(h, _RaisingHandler):
                logger.removeHandler(h)
