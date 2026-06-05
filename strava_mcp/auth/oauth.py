"""OAuth authorization-code flow with a one-shot local callback (research R5).

``auth`` builds the authorize URL from ``STRAVA_SCOPES``, opens it (or prints it
when headless), runs a single-request ``http.server`` on the loopback redirect
port to auto-capture ``code``/``scope``, then exchanges the code for tokens.
``127.0.0.1`` is whitelisted by Strava for dev redirects, so no tunnel is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from strava_mcp.auth.tokens import TokenSet, token_set_from_response
from strava_mcp.config import STRAVA_OAUTH_AUTHORIZE, STRAVA_OAUTH_TOKEN, Settings


@dataclass(frozen=True)
class CallbackResult:
    """What the redirect handed back."""

    code: str | None
    scope: str
    error: str | None


def build_authorize_url(settings: Settings, state: str) -> str:
    """Construct the Strava consent URL for the requested scopes."""
    params = {
        "client_id": settings.strava_client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": settings.strava_scopes,
        "state": state,
    }
    return f"{STRAVA_OAUTH_AUTHORIZE}?{urlencode(params)}"


class _CallbackHandler(BaseHTTPRequestHandler):
    captured: CallbackResult | None = None
    expected_state: str = ""

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        query = parse_qs(urlparse(self.path).query)
        state = query.get("state", [""])[0]
        error = query.get("error", [None])[0]
        code = query.get("code", [None])[0]
        scope = query.get("scope", [""])[0]

        if error is None and state != type(self).expected_state:
            error = "state_mismatch"
            code = None

        type(self).captured = CallbackResult(code=code, scope=scope, error=error)

        body = (
            b"<html><body><h2>Strava authorization received.</h2>"
            b"<p>You may close this tab and return to the terminal.</p></body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silence default stderr logging
        return


def run_callback_server(host: str, port: int, state: str) -> CallbackResult:
    """Serve exactly one redirect request and return the captured result."""
    _CallbackHandler.captured = None
    _CallbackHandler.expected_state = state
    server = HTTPServer((host, port), _CallbackHandler)
    try:
        server.handle_request()
    finally:
        server.server_close()
    return _CallbackHandler.captured or CallbackResult(None, "", "no_callback")


def exchange_code(
    settings: Settings,
    code: str,
    *,
    scope: str,
    client: httpx.Client | None = None,
) -> TokenSet:
    """Exchange an authorization code for a token set."""
    owned = client is None
    http_client = client or httpx.Client(timeout=30.0)
    try:
        resp = http_client.post(
            STRAVA_OAUTH_TOKEN,
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    finally:
        if owned:
            http_client.close()
    # Prefer the scope echoed back by the token endpoint, else the redirect's.
    granted = payload.get("scope") or scope
    return token_set_from_response(payload, scope=granted)
