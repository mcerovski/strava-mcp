"""T010 dashboard subcommand wiring + actionable missing-DB / port-in-use failures."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from strava_mcp.__main__ import build_parser
from strava_mcp.config import Settings
from strava_mcp.dashboard.server import run_dashboard


def test_subcommand_registered() -> None:
    args = build_parser().parse_args(["dashboard"])
    assert args.command == "dashboard"


def test_missing_db_is_actionable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(strava_db_path=str(tmp_path / "nope.db"))
    rc = run_dashboard(settings)
    out = capsys.readouterr().out
    assert rc == 1
    assert "No mirror found" in out
    assert "uv run strava-mcp serve" in out


def test_port_in_use_is_actionable(
    db_path: Path,
    conn: object,  # noqa: ARG001 - ensures the DB file exists
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Hold a loopback port so the dashboard bind fails deterministically.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    try:
        settings = Settings(
            strava_db_path=str(db_path), dashboard_host="127.0.0.1", dashboard_port=port
        )
        rc = run_dashboard(settings)
    finally:
        sock.close()
    out = capsys.readouterr().out
    assert rc == 1
    assert f"Port {port} is in use" in out
