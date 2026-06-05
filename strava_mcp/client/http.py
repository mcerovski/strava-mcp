"""Thin Strava HTTP client: base URL, bearer auth, JSON decode, Fault mapping.

Only the worker uses this client (Constitution I — tools never call Strava).
Token refresh (US2) and rate limiting (US3) hook in via the ``token_provider``
and ``rate_limiter`` injection points; this module owns request mechanics only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import httpx

from strava_mcp.config import STRAVA_API_BASE


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

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None) -> Any:
        if self._rate_limiter is not None:
            self._rate_limiter.before_request()
        url = path if path.startswith("http") else f"{self._base_url}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self._token_provider()}"}
        response = self._client.request(method, url, params=params, headers=headers)
        if self._rate_limiter is not None:
            self._rate_limiter.record(response.headers)
        if response.status_code >= 400:
            raise _map_fault(response)
        if not response.content:
            return None
        return response.json()

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET a Strava resource, returning decoded JSON."""
        return self._request("GET", path, params=params)
