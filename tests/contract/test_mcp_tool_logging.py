"""T011a [US1] MCP tool wrapper + serve startup failure logging.

FR-003, SC-001: (a) a tool that raises logs an ERROR human-log line naming the tool;
(b) ``run_server`` with a missing required scope logs the actionable startup error and
exits non-zero.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from strava_mcp.config import Settings
from strava_mcp.mcp import server


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


def test_tool_exception_logs_error_naming_tool(caplog: pytest.LogCaptureFixture) -> None:
    @server.instrument("get_activity")
    def boom(id: int) -> dict[str, object]:
        raise ValueError("kaboom")

    with caplog.at_level(logging.INFO, logger="strava_mcp"):
        with pytest.raises(ValueError):
            boom(1)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("get_activity" in r.getMessage() for r in errors)


def test_tool_success_logs_info_naming_tool(caplog: pytest.LogCaptureFixture) -> None:
    @server.instrument("get_athlete")
    def ok() -> dict[str, object]:
        return {"ok": True}

    with caplog.at_level(logging.INFO, logger="strava_mcp"):
        assert ok() == {"ok": True}

    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("get_athlete" in r.getMessage() for r in infos)


def test_serve_missing_scope_logs_and_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(
        strava_client_id="c",
        strava_client_secret="s",
        strava_db_path=str(tmp_path / "strava.db"),
        strava_log_path=str(tmp_path / "strava-mcp.log"),
        strava_audit_path=str(tmp_path / "audit.log"),
        _env_file=None,  # type: ignore[call-arg]
    )

    # run_server configures real logging (propagate=False), so assert on stderr,
    # where both the actionable message and the ERROR log line land.
    rc = server.run_server(settings)

    assert rc == 1
    err = capsys.readouterr().err
    assert "scope" in err.lower()
    assert "refusing to serve" in err
    assert "uv run strava-mcp auth" in err
