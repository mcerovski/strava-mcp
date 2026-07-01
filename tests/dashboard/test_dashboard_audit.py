"""T020 [US2] Dashboard audit: one interaction event per page load.

FR-013: a page load emits exactly one dashboard/interaction event with mandatory
fields (ts, stream, event, req_id) and stream-specific fields (method, path,
query, status, ms, client).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from strava_mcp import audit

from tests.dashboard.conftest import invoke_request

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


def test_page_load_emits_exactly_one_interaction_event(
    tmp_path: Path, conn: sqlite3.Connection, db_path: Path
) -> None:
    audit.setup_audit(tmp_path / "audit.log")
    invoke_request(db_path, "/")

    records = _flush_and_read(tmp_path / "audit.log")
    interactions = [r for r in records if r.get("event") == "interaction"]
    assert len(interactions) == 1

    ev = interactions[0]
    # Mandatory fields
    for field in _MANDATORY:
        assert field in ev
    assert ev["stream"] == "dashboard"
    assert ev["event"] == "interaction"

    # Stream-specific fields
    assert ev["method"] == "GET"
    assert ev["path"] == "/"
    assert "status" in ev
    assert "ms" in ev and isinstance(ev["ms"], int) and ev["ms"] >= 0
    assert "client" in ev


def test_interaction_event_includes_client_address(
    tmp_path: Path, conn: sqlite3.Connection, db_path: Path
) -> None:
    audit.setup_audit(tmp_path / "audit.log")
    invoke_request(db_path, "/", client_address=("127.0.0.1", 54321))

    records = _flush_and_read(tmp_path / "audit.log")
    ev = records[0]
    assert ev["client"] == "127.0.0.1"


def test_interaction_event_status_reflects_response_code(
    tmp_path: Path, conn: sqlite3.Connection, db_path: Path
) -> None:
    audit.setup_audit(tmp_path / "audit.log")
    invoke_request(db_path, "/")

    records = _flush_and_read(tmp_path / "audit.log")
    ev = records[0]
    assert ev["status"] == 200


def test_not_found_page_emits_interaction_with_404(
    tmp_path: Path, conn: sqlite3.Connection, db_path: Path
) -> None:
    audit.setup_audit(tmp_path / "audit.log")
    invoke_request(db_path, "/nonexistent")

    records = _flush_and_read(tmp_path / "audit.log")
    ev = records[0]
    assert ev["status"] == 404


def test_interaction_req_id_is_stable_within_one_request(
    tmp_path: Path, conn: sqlite3.Connection, db_path: Path
) -> None:
    """Each dashboard request has exactly one req_id (correlation_scope wraps do_GET)."""
    audit.setup_audit(tmp_path / "audit.log")
    invoke_request(db_path, "/")
    invoke_request(db_path, "/")

    records = _flush_and_read(tmp_path / "audit.log")
    assert len(records) == 2
    req_ids = [r["req_id"] for r in records]
    # 2 different req_ids for 2 requests
    assert req_ids[0] != req_ids[1]
