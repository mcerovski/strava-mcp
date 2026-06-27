"""T010 [US1] A swallowed non-rate-limit worker failure is logged with context.

FR-005, SC-001: ``_run_with_cooldown`` must log a non-rate-limit failure with
exception context (traceback / ``exc_info``) while still skipping-and-continuing.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from strava_mcp.config import Settings
from strava_mcp.sync.orchestrator import Orchestrator


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


def _settings(db_path: Path) -> Settings:
    return Settings(
        strava_client_id="c",
        strava_client_secret="s",
        strava_db_path=str(db_path),
        _env_file=None,  # type: ignore[call-arg]
    )


def test_swallowed_error_is_logged_with_exc_info_and_continues(
    conn: sqlite3.Connection, db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    orch = Orchestrator(conn, object(), _settings(db_path))

    def boom() -> None:
        raise RuntimeError("disk gremlin")

    with caplog.at_level(logging.ERROR, logger="strava_mcp"):
        # Returns normally — skip-and-continue is preserved (no raise).
        orch._run_with_cooldown(boom, label="enrichment activity 123")

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any(
        "enrichment activity 123" in r.getMessage() and "skipping" in r.getMessage()
        for r in errors
    )
    # Exception context (traceback) was captured.
    assert any(r.exc_info is not None for r in errors)
