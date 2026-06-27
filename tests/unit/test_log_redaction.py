"""T072 Log redaction never emits token-like secrets to stdout or the file.

Closes SC-010 / FR-023; pairs with the logging dual sink (T009).
T024 [US3] also extends this file: a token/secret routed through an audit field is
redacted in the serialized audit.log line (both sinks share redaction, FR-015, SC-003).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from strava_mcp import audit
from strava_mcp.logging import _scrub, setup_logging


@pytest.fixture(autouse=True)
def _reset_logger() -> None:
    """Isolate the shared ``strava_mcp`` logger between tests.

    Resets propagate=True so pytest captures via the root logger instead of
    injecting its own LogCaptureHandler directly onto the strava_mcp logger.
    If propagate stays False (left by a previous run_server/run_dashboard call),
    pytest's injected handler makes setup_logging's ``if logger.handlers`` guard
    fire early and skip file-handler creation.
    """
    logger = logging.getLogger("strava_mcp")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger.propagate = True


def test_scrub_removes_bearer_and_token_fields() -> None:
    assert "secrettoken123abc" not in _scrub("Authorization: Bearer secrettoken123abc")
    assert "[REDACTED]" in _scrub("Authorization: Bearer secrettoken123abc")
    assert "myrefresh" not in _scrub('{"refresh_token": "myrefresh"}')
    assert "deadbeefdeadbeefdeadbeefdeadbeef" not in _scrub(
        "token=deadbeefdeadbeefdeadbeefdeadbeef"
    )


def test_no_secret_reaches_stdout_or_file(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    log_path = tmp_path / "strava-mcp.log"
    logger = setup_logging(log_path, level=logging.INFO)
    secret = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"  # 32-hex, token-like
    logger.info("refreshing with Bearer %s", secret)
    logger.info('persisted {"access_token": "topsecretvalue"}')

    for handler in logger.handlers:
        handler.flush()

    file_text = log_path.read_text(encoding="utf-8")
    captured = capsys.readouterr()

    assert secret not in file_text
    assert "topsecretvalue" not in file_text
    assert secret not in captured.err and secret not in captured.out
    assert "[REDACTED]" in file_text


def test_setup_logging_is_idempotent(tmp_path: Path) -> None:
    log_path = tmp_path / "strava-mcp.log"
    a = setup_logging(log_path)
    handler_count = len(a.handlers)
    b = setup_logging(log_path)
    assert a is b
    assert len(b.handlers) == handler_count  # no duplicate handlers


# --- T024 [US3] Audit sink redaction ---


@pytest.fixture(autouse=False)
def _reset_audit_logger() -> pytest.FixtureRequest:
    """Isolate the ``strava_mcp.audit`` logger for T024 tests (setup + teardown)."""
    logger = logging.getLogger("strava_mcp.audit")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    yield  # type: ignore[misc]
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def test_token_in_audit_field_is_redacted_in_audit_log(
    tmp_path: Path, _reset_audit_logger: None
) -> None:
    """T024: a bearer token routed through an audit field is redacted (FR-015, SC-003)."""
    audit.setup_audit(tmp_path / "audit.log")
    token = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"  # 32-hex, token-like
    audit.emit("strava", "response", error=f"Authorization: Bearer {token}")

    for handler in logging.getLogger("strava_mcp.audit").handlers:
        handler.flush()

    raw = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert token not in raw
    assert "[REDACTED]" in raw


def test_access_token_value_in_audit_field_is_redacted(
    tmp_path: Path, _reset_audit_logger: None
) -> None:
    """T024: an access_token value routed through an audit field is redacted (SC-003)."""
    audit.setup_audit(tmp_path / "audit.log")
    secret = "topsecretaccesstokenvalue"
    audit.emit("mcp", "request", tool="get_athlete", args={"access_token": secret})

    for handler in logging.getLogger("strava_mcp.audit").handlers:
        handler.flush()

    raw = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert secret not in raw
