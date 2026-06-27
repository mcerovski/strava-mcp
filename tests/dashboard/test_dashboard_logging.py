"""T011 [US1] A dashboard request emits one INFO line with method/path/status/latency.

FR-004.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.dashboard.conftest import invoke_request


@pytest.fixture(autouse=True)
def _capture_strava_logs() -> Iterator[None]:
    lg = logging.getLogger("strava_mcp")
    saved = (lg.handlers[:], lg.propagate, lg.level)
    lg.handlers = []
    lg.propagate = True
    try:
        yield
    finally:
        lg.handlers, lg.propagate, lg.level = saved


def test_request_logs_one_info_line(
    conn: sqlite3.Connection, db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="strava_mcp"):
        invoke_request(db_path, "/")

    infos = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.INFO and "GET" in r.getMessage() and r.name != "strava_mcp.audit"
    ]
    assert len(infos) == 1
    msg = infos[0]
    assert "GET" in msg and "/" in msg and "200" in msg and "ms" in msg and "127.0.0.1" in msg
