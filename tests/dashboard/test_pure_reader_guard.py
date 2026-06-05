"""T009 The dashboard module never imports the client or sync layer.

The dashboard is a pure DB reader (Constitution I). Enforced structurally by
checking imports across every module in strava_mcp/dashboard/.
"""

from __future__ import annotations

import ast
from pathlib import Path

import strava_mcp.dashboard as dashboard_pkg

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
