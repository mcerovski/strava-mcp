"""CLI entrypoints: ``auth`` (one-time OAuth) and ``serve`` (MCP server + worker).

Run via ``uv run strava-mcp <command>`` (contracts/cli.md). Sync runs *inside*
``serve``; there is no standalone sync command.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import webbrowser

from strava_mcp.auth import missing_scopes
from strava_mcp.auth.oauth import build_authorize_url, exchange_code, run_callback_server
from strava_mcp.auth.tokens import TokenStore
from strava_mcp.client.http import StravaClient, StravaError
from strava_mcp.config import get_settings
from strava_mcp.db import engine


def _cmd_auth(_args: argparse.Namespace) -> int:
    """Complete the full-scope OAuth flow and persist tokens (US1)."""
    settings = get_settings()
    if not settings.strava_client_id or not settings.strava_client_secret:
        print("STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET must be set in .env", file=sys.stderr)
        return 1

    state = secrets.token_urlsafe(24)
    url = build_authorize_url(settings, state)

    print(f"Opening Strava consent for scopes: {settings.strava_scopes}")
    opened = False
    try:
        opened = webbrowser.open(url)
    except Exception:
        opened = False
    if not opened:
        print("Open this URL in your browser to authorize:")
        print(f"  {url}")

    print(f"Waiting for the redirect on {settings.redirect_uri} ...")
    result = run_callback_server(settings.oauth_redirect_host, settings.oauth_redirect_port, state)

    if result.error or not result.code:
        print(f"Authorization failed: {result.error or 'no code returned'}", file=sys.stderr)
        return 1

    tokens = exchange_code(settings, result.code, scope=result.scope)

    conn = engine.connect(settings.strava_db_path)
    try:
        store = TokenStore(conn, settings)
        store.save(tokens)

        # Verify with a 1-activity probe read (expect HTTP 200).
        client = StravaClient(store.access_token)
        try:
            client.get("/athlete/activities", params={"per_page": 1})
        except StravaError as exc:
            print(f"Verification read failed: {exc}", file=sys.stderr)
            return 1
        finally:
            client.close()
    finally:
        conn.close()

    print(f"Authorized. Granted scopes: {tokens.scope}")
    absent = missing_scopes(tokens.scope)
    if absent:
        print(
            "WARNING: some requested scopes were not granted: " + ", ".join(absent),
            file=sys.stderr,
        )
    print("Tokens persisted. Probe read succeeded.")
    return 0


def _cmd_serve(_args: argparse.Namespace) -> int:
    """Start the MCP server + background worker (US2+)."""
    # Imported lazily so `auth` does not pull in the server/worker stack.
    from strava_mcp.mcp.server import run_server

    return run_server()


def _cmd_dashboard(_args: argparse.Namespace) -> int:
    """Start the read-only data dashboard (separate process from serve)."""
    # Imported lazily so other commands do not pull in the dashboard stack.
    from strava_mcp.dashboard.server import run_dashboard

    return run_dashboard()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="strava-mcp", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("auth", help="Authorize once with Strava and persist tokens.")
    sub.add_parser("serve", help="Run the MCP server and the background sync worker.")
    sub.add_parser("dashboard", help="Run the read-only data dashboard (local web UI).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "auth":
        return _cmd_auth(args)
    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "dashboard":
        return _cmd_dashboard(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
