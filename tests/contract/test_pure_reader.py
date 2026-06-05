"""T066 No module under strava_mcp/mcp/tools/ imports the client or sync layer.

The architectural invariant (Constitution I, ADR 0001): MCP tools are pure DB
readers and never call Strava. Enforced structurally by checking imports.
"""

from __future__ import annotations

import ast
from pathlib import Path

import strava_mcp.mcp.tools as tools_pkg

_TOOLS_DIR = Path(tools_pkg.__file__).parent
_FORBIDDEN = ("strava_mcp.client", "strava_mcp.sync")


def _imported_modules(source: str) -> set[str]:
    names: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_tools_never_import_client_or_sync() -> None:
    offenders: dict[str, set[str]] = {}
    for path in _TOOLS_DIR.glob("*.py"):
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
