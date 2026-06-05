"""T072 Log redaction never emits token-like secrets to stdout or the file.

Closes SC-010 / FR-023; pairs with the logging dual sink (T009).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from strava_mcp.logging import _scrub, setup_logging


@pytest.fixture(autouse=True)
def _reset_logger() -> None:
    """Isolate the shared ``strava_mcp`` logger between tests."""
    logger = logging.getLogger("strava_mcp")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def test_scrub_removes_bearer_and_token_fields() -> None:
    assert "secrettoken123abc" not in _scrub("Authorization: Bearer secrettoken123abc")
    assert "[REDACTED]" in _scrub("Authorization: Bearer secrettoken123abc")
    assert "myrefresh" not in _scrub('{"refresh_token": "myrefresh"}')
    assert "deadbeefdeadbeefdeadbeefdeadbeef" not in _scrub(
        "token=deadbeefdeadbeefdeadbeefdeadbeef"
    )


def test_no_secret_reaches_stdout_or_file(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "strava.db"
    logger = setup_logging(db_path, level=logging.INFO)
    secret = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"  # 32-hex, token-like
    logger.info("refreshing with Bearer %s", secret)
    logger.info('persisted {"access_token": "topsecretvalue"}')

    for handler in logger.handlers:
        handler.flush()

    log_file = db_path.parent / "strava-mcp.log"
    file_text = log_file.read_text(encoding="utf-8")
    captured = capsys.readouterr()

    assert secret not in file_text
    assert "topsecretvalue" not in file_text
    assert secret not in captured.err and secret not in captured.out
    assert "[REDACTED]" in file_text


def test_setup_logging_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "strava.db"
    a = setup_logging(db_path)
    handler_count = len(a.handlers)
    b = setup_logging(db_path)
    assert a is b
    assert len(b.handlers) == handler_count  # no duplicate handlers
