"""Local data dashboard — a pure-reader, browser-based view of the mirror.

This module is a fourth read-only surface alongside ``strava_mcp/mcp/``. Like the
MCP tools it:

- MUST NOT import ``strava_mcp.client`` or ``strava_mcp.sync`` (enforced by the
  pure-reader guard test),
- MUST NOT write to the database (every connection is opened read-only), and
- MUST NOT call Strava.

It reads the same WAL SQLite mirror that ``serve`` populates, via per-request
read-only connections, so the single writer (the sync worker) is never blocked.
Run it with ``uv run strava-mcp dashboard`` (separate process from ``serve``).
"""

from __future__ import annotations
