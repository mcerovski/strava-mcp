"""HTTP server for the read-only dashboard.

A ``ThreadingHTTPServer`` bound to the loopback ``DASHBOARD_HOST:DASHBOARD_PORT``
with a small explicit router. Each request reads the mirror through read-only
connections (opened inside ``queries``), so the sync worker (single writer) is
never blocked. No request writes the DB or calls Strava.
"""

from __future__ import annotations

import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from strava_mcp.config import Settings, get_settings
from strava_mcp.dashboard import handlers
from strava_mcp.logging import get_logger, setup_logging

log = get_logger()

_STATIC_DIR = Path(__file__).parent / "static"
_ACTIVITY_RE = re.compile(r"^/activity/(\d+)/?$")


class DashboardServer(ThreadingHTTPServer):
    """Threading HTTP server carrying the mirror path for handlers."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], db_path: Path | str) -> None:
        self.db_path = db_path
        super().__init__(address, DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "strava-mcp-dashboard"

    @property
    def _db_path(self) -> Path | str:
        server: DashboardServer = self.server  # type: ignore[assignment]
        return server.db_path

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        log.debug("dashboard %s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _serve_css(self) -> None:
        try:
            css = (_STATIC_DIR / "app.css").read_text(encoding="utf-8")
        except OSError:
            self._send(404, "/* not found */", "text/css; charset=utf-8")
            return
        self._send(200, css, "text/css; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        parts = urlsplit(self.path)
        path = parts.path
        params = parse_qs(parts.query)
        db = self._db_path

        try:
            if path == "/static/app.css":
                self._serve_css()
                return
            if path == "/":
                status, html = handlers.handle_list(db, params)
            elif path in ("/timeline", "/timeline/"):
                status, html = handlers.handle_timeline(db, params)
            elif path in ("/sync", "/sync/"):
                status, html = handlers.handle_sync(db)
            elif (m := _ACTIVITY_RE.match(path)) is not None:
                status, html = handlers.handle_detail(db, int(m.group(1)))
            else:
                status, html = handlers.handle_not_found(db, path)
        except Exception:  # pragma: no cover - defensive; never leak a stack trace
            log.exception("dashboard request failed: %s", path)
            self._send(500, "<h1>Internal error</h1><p>See the server log.</p>")
            return
        self._send(status, html)

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib signature
        self.do_GET()


def _verify_db(db_path: Path | str) -> bool:
    """Confirm the mirror exists and is openable read-only."""
    try:
        conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False


def run_dashboard(settings: Settings | None = None) -> int:
    """Entry point for ``strava-mcp dashboard``."""
    settings = settings or get_settings()
    setup_logging(settings.strava_db_path)

    if not _verify_db(settings.strava_db_path):
        print(
            f"No mirror found at {settings.strava_db_path}. "
            "Run 'uv run strava-mcp serve' first to create and populate it.",
        )
        log.error("dashboard: mirror not found at %s", settings.strava_db_path)
        return 1

    address = (settings.dashboard_host, settings.dashboard_port)
    try:
        server = DashboardServer(address, settings.strava_db_path)
    except OSError:
        print(
            f"Port {settings.dashboard_port} is in use. "
            "Set DASHBOARD_PORT to a free port and retry.",
        )
        log.error("dashboard: port %s in use", settings.dashboard_port)
        return 1

    url = f"http://{settings.dashboard_host}:{settings.dashboard_port}"
    print(f"dashboard on {url}")
    log.info("dashboard on %s", url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        log.info("dashboard shutting down")
    finally:
        server.server_close()
    return 0
