"""Auth package: scope-sufficiency helpers reused by ``auth`` and ``serve``.

The required read scopes are fixed in :mod:`strava_mcp.config`. ``auth`` checks
the *granted* scope from the redirect (users can uncheck boxes) and warns if it
is narrower; ``serve`` refuses to start when a required scope is missing
(research R6, contracts/cli.md).
"""

from __future__ import annotations

from strava_mcp.config import REQUIRED_SCOPES


def parse_scopes(granted: str | list[str] | None) -> set[str]:
    """Normalize a granted scope (comma- or space-separated string, or list)."""
    if granted is None:
        return set()
    if isinstance(granted, str):
        parts = granted.replace(",", " ").split()
    else:
        parts = list(granted)
    return {p.strip() for p in parts if p.strip()}


def missing_scopes(granted: str | list[str] | None) -> list[str]:
    """Required scopes absent from ``granted``, in canonical order."""
    have = parse_scopes(granted)
    return [s for s in REQUIRED_SCOPES if s not in have]


def has_required_scopes(granted: str | list[str] | None) -> bool:
    return not missing_scopes(granted)
