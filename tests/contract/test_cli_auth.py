"""T011 [US1] Contract test: authorize URL, callback capture, exchange, scope report."""

from __future__ import annotations

import threading
from urllib.parse import parse_qs, urlparse

import httpx
from strava_mcp.auth import has_required_scopes, missing_scopes
from strava_mcp.auth.oauth import build_authorize_url, exchange_code, run_callback_server
from strava_mcp.config import Settings


def _settings(**overrides: object) -> Settings:
    base = dict(strava_client_id="cid", strava_client_secret="csecret", _env_file=None)
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_authorize_url_has_required_params() -> None:
    settings = _settings()
    url = build_authorize_url(settings, state="xyz")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["cid"]
    assert q["response_type"] == ["code"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8721"]
    assert q["state"] == ["xyz"]
    assert "activity:read_all" in q["scope"][0]


def test_callback_server_captures_code_and_scope() -> None:
    captured: dict[str, object] = {}

    def serve() -> None:
        captured["result"] = run_callback_server("127.0.0.1", 8755, state="st8")

    t = threading.Thread(target=serve)
    t.start()
    # Hit the one-shot callback with a Strava-style redirect.
    httpx.get(
        "http://127.0.0.1:8755/",
        params={"code": "the-code", "scope": "read,activity:read_all", "state": "st8"},
    )
    t.join(timeout=5)
    result = captured["result"]
    assert result.code == "the-code"  # type: ignore[union-attr]
    assert result.error is None  # type: ignore[union-attr]
    assert "activity:read_all" in result.scope  # type: ignore[union-attr]


def test_callback_rejects_state_mismatch() -> None:
    captured: dict[str, object] = {}

    def serve() -> None:
        captured["result"] = run_callback_server("127.0.0.1", 8756, state="expected")

    t = threading.Thread(target=serve)
    t.start()
    httpx.get("http://127.0.0.1:8756/", params={"code": "c", "state": "wrong"})
    t.join(timeout=5)
    assert captured["result"].error == "state_mismatch"  # type: ignore[union-attr]


def test_exchange_code_returns_token_set() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert b"grant_type=authorization_code" in request.content
        return httpx.Response(
            200,
            json={
                "access_token": "acc",
                "refresh_token": "ref",
                "expires_at": 4_000_000_000,
                "scope": "read,read_all,profile:read_all,activity:read,activity:read_all",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    tokens = exchange_code(_settings(), "the-code", scope="read", client=client)
    assert tokens.access_token == "acc"
    assert has_required_scopes(tokens.scope)


def test_scope_report_flags_narrowed_grant() -> None:
    assert missing_scopes("read,activity:read") == [
        "read_all",
        "profile:read_all",
        "activity:read_all",
    ]
    assert has_required_scopes("read,read_all,profile:read_all,activity:read,activity:read_all")
