"""FastMCP server: scope-check-or-exit, register read tools, own the worker.

``serve`` binds a ``streamable-http`` FastMCP app to the loopback
``MCP_HOST:MCP_PORT``, refuses to start if the stored token lacks a required
scope, and starts the single background worker thread (contracts/cli.md).
Tool functions are pure DB reads; only the worker calls Strava.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

from strava_mcp.auth import missing_scopes
from strava_mcp.auth.tokens import TokenStore
from strava_mcp.config import Settings, get_settings
from strava_mcp.db import engine
from strava_mcp.logging import get_logger, setup_logging
from strava_mcp.mcp.tools import activities as activity_tools
from strava_mcp.mcp.tools import athlete as athlete_tools
from strava_mcp.mcp.tools import gear as gear_tools
from strava_mcp.mcp.tools import routes as route_tools
from strava_mcp.mcp.tools import segments as segment_tools
from strava_mcp.mcp.tools import streams as stream_tools
from strava_mcp.mcp.tools import summaries as summary_tools
from strava_mcp.mcp.tools import sync as sync_tools

log = get_logger()


def check_scopes(settings: Settings) -> list[str]:
    """Return required scopes missing from the stored token.

    A non-empty list means ``serve`` must refuse to start. An absent token (the
    single DB row) also counts as "all scopes missing" — the operator must run
    ``auth`` first. The DB row is the only token source; there is no env seed.
    """
    conn = engine.connect(settings.strava_db_path)
    try:
        tokens = TokenStore(conn, settings).read()
        if tokens is None:
            from strava_mcp.config import REQUIRED_SCOPES

            return list(REQUIRED_SCOPES)
        return missing_scopes(tokens.scope)
    finally:
        conn.close()


def build_app(db_path: Path | str, poll_event=None):  # type: ignore[no-untyped-def]
    """Construct the FastMCP app and register the read tools."""
    from fastmcp import FastMCP

    mcp = FastMCP("strava-mcp")
    register_tools(mcp, db_path, poll_event=poll_event)
    return mcp


def register_tools(mcp, db_path: Path | str, poll_event=None) -> None:  # type: ignore[no-untyped-def]
    """Register all MCP read tools, binding the DB path via closures.

    ``poll_event`` is the worker's nudge event; ``sync_now`` sets it.
    """

    @mcp.tool
    def get_athlete() -> dict[str, Any]:
        """Return the mirrored athlete profile, zones, and stats."""
        return athlete_tools.get_athlete(db_path)

    @mcp.tool
    def list_activities(
        after: str | int | None = None,
        before: str | int | None = None,
        sport_type: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """List enriched activities (newest first), filtered by date/sport."""
        return activity_tools.list_activities(
            db_path, after=after, before=before, sport_type=sport_type, limit=limit
        )

    @mcp.tool
    def get_activity(id: int) -> dict[str, Any]:
        """Return the full detail for one enriched activity."""
        return activity_tools.get_activity(db_path, id)

    @mcp.tool
    def get_laps(id: int) -> object:
        """Return the laps for one enriched activity."""
        return activity_tools.get_laps(db_path, id)

    @mcp.tool
    def get_activity_zones(id: int) -> object:
        """Return the heart-rate/power zones for one enriched activity."""
        return activity_tools.get_activity_zones(db_path, id)

    @mcp.tool
    def get_activity_streams(id: int, keys: list[str] | None = None) -> dict[str, Any]:
        """Return the stored streams for one enriched activity (optionally filtered)."""
        return stream_tools.get_activity_streams(db_path, id, keys)

    @mcp.tool
    def list_gear() -> list[dict[str, Any]]:
        """List the athlete's gear (bikes and shoes)."""
        return gear_tools.list_gear(db_path)

    @mcp.tool
    def get_gear(id: str) -> dict[str, Any]:
        """Return one gear item by id."""
        return gear_tools.get_gear(db_path, id)

    @mcp.tool
    def list_routes() -> list[dict[str, Any]]:
        """List the athlete's routes (metadata + polyline)."""
        return route_tools.list_routes(db_path)

    @mcp.tool
    def get_route(id: str) -> dict[str, Any]:
        """Return one route by id (metadata + polyline)."""
        return route_tools.get_route(db_path, id)

    @mcp.tool
    def list_starred_segments() -> list[dict[str, Any]]:
        """List the athlete's starred segments (full detail)."""
        return segment_tools.list_starred_segments(db_path)

    @mcp.tool
    def get_segment(id: int) -> dict[str, Any]:
        """Return a segment: full detail if starred, else encountered summary."""
        return segment_tools.get_segment(db_path, id)

    @mcp.tool
    def list_segment_efforts(segment_id: int) -> list[dict[str, Any]]:
        """Return the athlete's efforts on a given segment."""
        return segment_tools.list_segment_efforts(db_path, segment_id)

    @mcp.tool
    def sync_status() -> dict[str, Any]:
        """Report backfill/poll progress, counts, rate budget, and cooldown."""
        return sync_tools.sync_status(db_path)

    @mcp.tool
    def sync_now() -> dict[str, Any]:
        """Nudge the worker to run the forward POLL immediately."""
        return sync_tools.sync_now(db_path, poll_event)

    @mcp.tool
    def summarize_training(
        period: str = "weekly", sport_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Per-period training rollups (count/distance/time/elevation)."""
        return summary_tools.summarize_training(db_path, period=period, sport_type=sport_type)


def _prewarm_http_stack() -> None:
    """Fully import the HTTP client stack on the main thread, single-threaded.

    Constructing the first ``httpx.Client`` lazily imports ``httpcore → anyio``.
    Doing that for the first time inside the worker thread while uvicorn
    concurrently imports ``anyio`` on the main thread races on CPython's import
    lock and trips a ``_DeadlockError`` (observed on 3.14). Exercising the same
    transport-init path here, before any thread starts, removes the race.
    """
    import httpx

    httpx.Client().close()


def run_server(settings: Settings | None = None) -> int:
    """Entry point for ``strava-mcp serve``."""
    settings = settings or get_settings()
    setup_logging(settings.strava_db_path)

    absent = check_scopes(settings)
    if absent:
        print("run uv run strava-mcp auth", file=sys.stderr)
        log.error("insufficient scope (missing: %s); refusing to serve", ",".join(absent))
        return 1

    # Ensure the DB/schema exist before the worker and tools touch it.
    engine.connect(settings.strava_db_path).close()

    # Import the HTTP client stack on the main thread before starting the worker.
    _prewarm_http_stack()

    stop_event = threading.Event()
    from strava_mcp.sync.orchestrator import Worker

    worker = Worker(settings, stop_event=stop_event)
    worker.start()

    app = build_app(settings.strava_db_path, poll_event=worker.poll_event)
    log.info("serving MCP on http://%s:%s", settings.mcp_host, settings.mcp_port)
    try:
        app.run(transport="http", host=settings.mcp_host, port=settings.mcp_port)
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        log.info("shutting down")
    finally:
        stop_event.set()
        worker.join(timeout=5)
    return 0
