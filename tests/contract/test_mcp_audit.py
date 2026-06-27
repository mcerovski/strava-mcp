"""T019 [US2] MCP instrument wrapper: request+response audit events, no Strava call.

FR-011, FR-008: a tool invocation emits mcp/request + mcp/response sharing one req_id;
the call issues no Strava request (tools are pure DB readers), so no cross-stream
correlation is asserted. Fields: tool name, sanitized args, status, ms.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

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


def _flush_and_read(path: Path) -> list[dict[str, Any]]:
    for handler in logging.getLogger("strava_mcp.audit").handlers:
        handler.flush()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_tool_success_emits_mcp_request_and_response(tmp_path: Path) -> None:
    audit.setup_audit(tmp_path / "audit.log")

    @server.instrument("get_activity")
    def get_activity(id: int) -> dict[str, object]:
        return {"id": id, "name": "Test"}

    get_activity(42)

    records = _flush_and_read(tmp_path / "audit.log")
    assert len(records) == 2

    req = next(r for r in records if r["event"] == "request")
    resp = next(r for r in records if r["event"] == "response")

    # Both events share one req_id
    assert req["req_id"] == resp["req_id"]

    # Mandatory fields present in both
    for record in records:
        for field in _MANDATORY:
            assert field in record
        assert record["stream"] == "mcp"

    # Tool name in both events
    assert req["tool"] == "get_activity"
    assert resp["tool"] == "get_activity"

    # Args present (sanitized) in request
    assert "args" in req

    # Response has status=ok and ms
    assert resp["status"] == "ok"
    assert "ms" in resp
    assert isinstance(resp["ms"], int) and resp["ms"] >= 0


def test_tool_error_emits_error_status_in_response(tmp_path: Path) -> None:
    audit.setup_audit(tmp_path / "audit.log")

    @server.instrument("get_activity")
    def boom(id: int) -> dict[str, object]:
        raise ValueError("not found")

    with pytest.raises(ValueError):
        boom(99)

    records = _flush_and_read(tmp_path / "audit.log")
    assert len(records) == 2

    resp = next(r for r in records if r["event"] == "response")
    assert resp["status"] == "error"
    assert "error" in resp
    assert "ms" in resp
    # req_id still correlates the pair
    req = next(r for r in records if r["event"] == "request")
    assert req["req_id"] == resp["req_id"]


def test_tool_emits_no_strava_events(tmp_path: Path) -> None:
    """Tools are pure DB readers — no strava audit events emitted. (FR-011)"""
    audit.setup_audit(tmp_path / "audit.log")

    @server.instrument("list_activities")
    def list_activities() -> list[dict[str, object]]:
        return []

    list_activities()

    records = _flush_and_read(tmp_path / "audit.log")
    strava_events = [r for r in records if r["stream"] == "strava"]
    assert strava_events == []


def test_each_tool_call_gets_own_req_id(tmp_path: Path) -> None:
    """Each instrument invocation opens its own correlation_scope. (FR-008)"""
    audit.setup_audit(tmp_path / "audit.log")

    @server.instrument("get_athlete")
    def get_athlete() -> dict[str, object]:
        return {}

    get_athlete()
    get_athlete()

    records = _flush_and_read(tmp_path / "audit.log")
    # 2 calls × 2 events = 4 records
    assert len(records) == 4
    req_ids = {r["req_id"] for r in records}
    # 2 distinct req_ids — one per call
    assert len(req_ids) == 2
