"""Thin Strava HTTP client: base URL, bearer auth, JSON decode, Fault mapping.

Only the worker uses this client (Constitution I — tools never call Strava).
Token refresh (US2) and rate limiting (US3) hook in via the ``token_provider``
and ``rate_limiter`` injection points; this module owns request mechanics only.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from strava_mcp import audit
from strava_mcp.config import STRAVA_API_BASE
from strava_mcp.logging import get_logger

log = get_logger(__name__)


class StravaError(Exception):
    """A non-success Strava API response, carrying status and parsed Fault."""

    def __init__(self, status_code: int, message: str, fault: Any | None = None) -> None:
        super().__init__(f"Strava API error {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.fault = fault


class RateLimitExceeded(StravaError):
    """HTTP 429 — the read budget is exhausted; caller should cool down."""


class RateLimiter(Protocol):
    """Hook contract for rate-limit accounting (implemented in US3)."""

    def before_request(self) -> None:
        """Block/raise if the budget would be exceeded before sending."""

    def record(self, headers: httpx.Headers) -> None:
        """Update budget tracking from response rate-limit headers."""


def _map_fault(response: httpx.Response) -> StravaError:
    try:
        fault = response.json()
        message = (
            fault.get("message", response.reason_phrase)
            if isinstance(fault, dict)
            else response.reason_phrase
        )
    except Exception:
        fault = None
        message = response.reason_phrase or "request failed"
    if response.status_code == 429:
        return RateLimitExceeded(429, message, fault)
    return StravaError(response.status_code, message, fault)


class StravaClient:
    """Authenticated Strava API client (one per worker thread)."""

    def __init__(
        self,
        token_provider: Callable[[], str],
        *,
        base_url: str = STRAVA_API_BASE,
        client: httpx.Client | None = None,
        rate_limiter: RateLimiter | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._token_provider = token_provider
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)
        self._rate_limiter = rate_limiter

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> StravaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _rate_limit_snapshot(self) -> dict[str, Any] | None:
        snap = getattr(self._rate_limiter, "snapshot", None)
        return snap() if callable(snap) else None

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> Any:
        if self._rate_limiter is not None:
            self._rate_limiter.before_request()
        url = path if path.startswith("http") else f"{self._base_url}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self._token_provider()}"}
        # Never log headers or the bearer token (Constitution security clause).
        log.debug("%s %s params=%s", method, path, params)
        req_id = audit.current_req_id()
        query = audit.summarize_args(params) if params else None
        audit.emit("strava", "request", req_id=req_id, method=method, path=path, query=query)
        start = time.monotonic()
        try:
            response = self._client.request(method, url, params=params, headers=headers)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            log.error("%s %s -> transport error (%dms): %s", method, path, elapsed_ms, exc)
            audit.emit(
                "strava",
                "response",
                req_id=req_id,
                method=method,
                path=path,
                ms=elapsed_ms,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if self._rate_limiter is not None:
            self._rate_limiter.record(response.headers)
        status = response.status_code
        rate_limit = self._rate_limit_snapshot()
        if status >= 400:
            error = _map_fault(response)
            if status == 429:
                # Expected back-pressure; the worker cools down. Not an alarm.
                log.info("%s %s -> 429 (rate limited; cooling down)", method, path)
            elif status >= 500:
                log.error("%s %s -> %d (%dms): %s", method, path, status, elapsed_ms, error.message)
            else:
                log.warning(
                    "%s %s -> %d (%dms): %s", method, path, status, elapsed_ms, error.message
                )
            audit.emit(
                "strava",
                "response",
                req_id=req_id,
                method=method,
                path=path,
                status=status,
                ms=elapsed_ms,
                rate_limit=rate_limit,
                error=f"{type(error).__name__}: {error.message}",
            )
            raise error
        log.info("%s %s -> %d (%dms)", method, path, status, elapsed_ms)
        audit.emit(
            "strava",
            "response",
            req_id=req_id,
            method=method,
            path=path,
            status=status,
            ms=elapsed_ms,
            rate_limit=rate_limit,
        )
        if not response.content:
            return None
        return response.json()

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET a Strava resource, returning decoded JSON."""
        return self._request("GET", path, params=params)
