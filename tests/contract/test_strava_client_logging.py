"""T009 [US1] Strava HTTP client logs request/response/error at the right severity.

FR-001/002, SC-001: a non-2xx response logs WARNING (4xx) / ERROR (5xx) with method,
path, status, and fault message; a 200 logs INFO with latency; the bearer token never
appears in the log. T016/SC-007: DEBUG surfaces the per-request line.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import httpx
import pytest
from strava_mcp.client.http import StravaClient, StravaError

_TOKEN = "supersecretbearertoken123456"


@pytest.fixture(autouse=True)
def _capture_strava_logs() -> Iterator[None]:
    """Let pytest's caplog see the (propagate=False in prod) strava_mcp logger."""
    lg = logging.getLogger("strava_mcp")
    saved = (lg.handlers[:], lg.propagate, lg.level)
    lg.handlers = []
    lg.propagate = True
    try:
        yield
    finally:
        lg.handlers, lg.propagate, lg.level = saved


def _client(handler: object) -> StravaClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return StravaClient(lambda: _TOKEN, client=httpx.Client(transport=transport))


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records]


def test_success_logs_info_with_latency_and_no_token(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 1})

    with caplog.at_level(logging.DEBUG, logger="strava_mcp"):
        _client(handler).get("/athlete")

    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("-> 200" in r.getMessage() and "ms" in r.getMessage() for r in infos)
    assert all(_TOKEN not in m for m in _messages(caplog))


def test_4xx_logs_warning_with_method_path_status_fault(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Record Not Found"})

    with caplog.at_level(logging.DEBUG, logger="strava_mcp"):
        with pytest.raises(StravaError):
            _client(handler).get("/activities/123")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "GET" in m and "/activities/123" in m and "404" in m and "Record Not Found" in m
        for m in (r.getMessage() for r in warnings)
    )
    assert all(_TOKEN not in m for m in _messages(caplog))


def test_5xx_logs_error_with_method_path_status(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "Server Error"})

    with caplog.at_level(logging.DEBUG, logger="strava_mcp"):
        with pytest.raises(StravaError):
            _client(handler).get("/activities/9")

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("/activities/9" in m and "500" in m for m in (r.getMessage() for r in errors))


def test_429_is_not_logged_as_warning(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "Rate Limit Exceeded"})

    with caplog.at_level(logging.DEBUG, logger="strava_mcp"):
        with pytest.raises(StravaError):
            _client(handler).get("/athlete/activities")

    # An expected 429/cooldown is INFO/DEBUG, never WARNING/ERROR.
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_debug_level_surfaces_request_line(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with caplog.at_level(logging.DEBUG, logger="strava_mcp"):
        _client(handler).get("/athlete/activities", params={"per_page": 30})

    debug = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("/athlete/activities" in r.getMessage() for r in debug)
