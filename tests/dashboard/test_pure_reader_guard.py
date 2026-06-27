"""T009 The dashboard module never imports the client or sync layer.

The dashboard is a pure DB reader (Constitution I). Enforced structurally by
checking imports across every module in strava_mcp/dashboard/.

T026 [US3] also extends this file: enabling the audit trail does not cause any
write to the mirror DB from the dashboard (FR-017).
"""

from __future__ import annotations

import ast
import logging
import sqlite3
from pathlib import Path

import pytest
import strava_mcp.dashboard as dashboard_pkg
from strava_mcp import audit

_DASHBOARD_DIR = Path(dashboard_pkg.__file__).parent
_FORBIDDEN = ("strava_mcp.client", "strava_mcp.sync")


def _imported_modules(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_dashboard_never_imports_client_or_sync() -> None:
    offenders: dict[str, set[str]] = {}
    for path in _DASHBOARD_DIR.glob("*.py"):
        imported = _imported_modules(path.read_text(encoding="utf-8"))
        bad = {
            mod
            for mod in imported
            for forbidden in _FORBIDDEN
            if mod == forbidden or mod.startswith(forbidden + ".")
        }
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"pure-reader violation: {offenders}"


# --- T026 [US3] Enabling the audit trail does not write to the mirror DB ---


@pytest.fixture(autouse=False)
def _reset_audit_logger_guard() -> None:
    """Isolate the ``strava_mcp.audit`` logger for audit-trail DB-write tests."""
    logger = logging.getLogger("strava_mcp.audit")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def _db_row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return total row count per table as a snapshot."""
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def test_audit_trail_does_not_write_to_mirror_db(
    tmp_path: Path,
    conn: sqlite3.Connection,
    db_path: Path,
    _reset_audit_logger_guard: None,
) -> None:
    """T026: a dashboard request with audit enabled never mutates the mirror DB (FR-017)."""
    from tests.dashboard.conftest import invoke_request

    audit.setup_audit(tmp_path / "audit.log")
    before = _db_row_counts(conn)

    invoke_request(db_path, "/")
    invoke_request(db_path, "/sync")

    after = _db_row_counts(conn)
    assert before == after, f"mirror DB was mutated: {before} → {after}"
