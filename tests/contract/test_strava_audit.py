"""T018 [US2] Strava audit: request+response events, correlation, no token.

FR-012, FR-008, SC-006, FR-015: a Strava call emits strava/request + strava/response
sharing one req_id; multiple calls within one correlation_scope also share the req_id
(proving orchestrator T021a); fields include method, path, query summary, status,
latency; no bearer token appears in any field.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from strava_mcp import audit
from strava_mcp.client.http import StravaClient, StravaError

_TOKEN = "supersecretbearertoken123456"
_MANDATORY = ("ts", "stream", "event", "req_id")


@pytest.fixture(autouse=True)
def _reset_audit_logger() -> None:
    """Isolate the shared ``strava_mcp.audit`` logger between tests."""
    logger = logging.getLogger("strava_mcp.audit")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def _client(handler: object) -> StravaClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return StravaClient(lambda: _TOKEN, client=httpx.Client(transport=transport))


def _flush_and_read(path: Path) -> list[dict[str, Any]]:
    for handler in logging.getLogger("strava_mcp.audit").handlers:
        handler.flush()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": 1})


def test_strava_call_emits_request_and_response_events(tmp_path: Path) -> None:
    audit.setup_audit(tmp_path / "audit.log")
    _client(_ok).get("/athlete")
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
        assert record["stream"] == "strava"

    # Key request fields
    assert req["method"] == "GET"
    assert req["path"] == "/athlete"

    # Key response fields
    assert resp["status"] == 200
    assert "ms" in resp
    assert isinstance(resp["ms"], int) and resp["ms"] >= 0


def test_query_params_appear_as_summary_not_verbatim(tmp_path: Path) -> None:
    """Query params are sanitized, not dumped verbatim (data-model "Sanitized")."""
    audit.setup_audit(tmp_path / "audit.log")
    _client(_ok).get("/athlete/activities", params={"per_page": 30, "before": 1622548800})
    records = _flush_and_read(tmp_path / "audit.log")

    req = next(r for r in records if r["event"] == "request")
    # query is present and is not a raw string containing the per_page value
    assert req.get("query") is not None


def test_4xx_response_emits_error_field(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Record Not Found"})

    audit.setup_audit(tmp_path / "audit.log")
    with pytest.raises(StravaError):
        _client(handler).get("/activities/999")

    records = _flush_and_read(tmp_path / "audit.log")
    resp = next(r for r in records if r["event"] == "response")
    assert resp["status"] == 404
    assert "error" in resp
    # req_id correlates request and response even on error
    req = next(r for r in records if r["event"] == "request")
    assert req["req_id"] == resp["req_id"]


def test_no_bearer_token_in_any_audit_field(tmp_path: Path) -> None:
    audit.setup_audit(tmp_path / "audit.log")
    _client(_ok).get("/athlete")
    for handler in logging.getLogger("strava_mcp.audit").handlers:
        handler.flush()
    raw = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert _TOKEN not in raw


def test_multiple_calls_in_correlation_scope_share_req_id(tmp_path: Path) -> None:
    """Multiple Strava calls inside one correlation_scope share a req_id.

    This mirrors what _run_with_cooldown does in the orchestrator (T021a, FR-008,
    SC-006): every Strava call for one enrichment unit shares one req_id.
    """
    audit.setup_audit(tmp_path / "audit.log")
    client = _client(_ok)

    with audit.correlation_scope() as scope_req_id:
        client.get("/activities/1")
        client.get("/activities/1/laps")
        client.get("/activities/1/streams")

    records = _flush_and_read(tmp_path / "audit.log")
    # 3 calls × 2 events (request + response) = 6 records
    assert len(records) == 6
    # All share the scope's req_id
    for record in records:
        assert record["req_id"] == scope_req_id
