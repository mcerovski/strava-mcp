"""Rate-limit accounting + deterministic cooldown (research R2/R3, ADR; FR-015).

Strava returns read-tier headers formatted ``"15min,daily"``:
``X-ReadRateLimit-Usage`` / ``X-ReadRateLimit-Limit`` (and overall
``X-RateLimit-*``). The read tier is the binding budget for this read-only tool
(100/15min, 1000/day). On exhaustion (or a 429) the worker cools down to the
*known* next reset — the next quarter-hour boundary (15-min window) or the next
midnight UTC (daily window) — never a blind retry loop.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


class BudgetExhausted(Exception):
    """The read budget for a tier is spent; the worker must cool down."""

    def __init__(self, tier: str) -> None:
        super().__init__(f"read budget exhausted for tier: {tier}")
        self.tier = tier


@dataclass
class Usage:
    used: int
    limit: int

    def exhausted(self, cap: int | None = None) -> bool:
        ceiling = self.limit if cap is None else min(self.limit, cap)
        return self.used >= ceiling


def next_quarter_hour(now_epoch: float) -> int:
    """Epoch of the next ``:00/:15/:30/:45`` UTC boundary strictly after now."""
    dt = datetime.fromtimestamp(now_epoch, tz=UTC)
    minutes = (dt.minute // 15 + 1) * 15
    base = dt.replace(minute=0, second=0, microsecond=0)
    return int((base + timedelta(minutes=minutes)).timestamp())


def next_midnight_utc(now_epoch: float) -> int:
    """Epoch of the next ``00:00:00`` UTC strictly after now."""
    dt = datetime.fromtimestamp(now_epoch, tz=UTC)
    nxt = (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(nxt.timestamp())


def _parse_pair(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        a, b = (int(x.strip()) for x in value.split(",")[:2])
        return a, b
    except (ValueError, TypeError):
        return None


class RateLimitBudget:
    """Tracks read-tier usage and computes deterministic cooldown windows."""

    def __init__(
        self,
        *,
        max_requests: int = 900,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.max_requests = max_requests
        self._clock = clock
        self.read_15min: Usage | None = None
        self.read_daily: Usage | None = None
        self.overall_15min: Usage | None = None
        self.overall_daily: Usage | None = None
        # When the usage figures above were last observed. Used to treat them as
        # stale once their window boundary has passed, so the worker resumes
        # after a cooldown instead of re-cooling on pre-reset counts.
        self._recorded_at: float | None = None

    # --- RateLimiter protocol ---------------------------------------------
    def record(self, headers: Mapping[str, str]) -> None:
        lower = {k.lower(): v for k, v in headers.items()}
        self._recorded_at = self._clock()
        read_usage = _parse_pair(lower.get("x-readratelimit-usage"))
        read_limit = _parse_pair(lower.get("x-readratelimit-limit"))
        if read_usage and read_limit:
            self.read_15min = Usage(read_usage[0], read_limit[0])
            self.read_daily = Usage(read_usage[1], read_limit[1])
        all_usage = _parse_pair(lower.get("x-ratelimit-usage"))
        all_limit = _parse_pair(lower.get("x-ratelimit-limit"))
        if all_usage and all_limit:
            self.overall_15min = Usage(all_usage[0], all_limit[0])
            self.overall_daily = Usage(all_usage[1], all_limit[1])

    def before_request(self) -> None:
        tier = self.exhausted_tier()
        if tier is not None:
            raise BudgetExhausted(tier)

    # --- budget logic ------------------------------------------------------
    def _tier_stale(self, tier: str, now: float) -> bool:
        """True if the recorded usage predates the tier's last window reset.

        Strava's windows reset on fixed boundaries (quarter-hour / midnight UTC),
        so once the clock crosses the boundary that followed our last reading,
        that reading no longer reflects the current window and must not block.
        """
        if self._recorded_at is None:
            return False
        if tier == "daily":
            return next_midnight_utc(self._recorded_at) <= now
        return next_quarter_hour(self._recorded_at) <= now

    def exhausted_tier(self) -> str | None:
        """Return the exhausted tier (``'15min'``/``'daily'``) or None."""
        now = self._clock()
        if self.read_15min and self.read_15min.exhausted() and not self._tier_stale("15min", now):
            return "15min"
        if (
            self.read_daily
            and self.read_daily.exhausted(cap=self.max_requests)
            and not self._tier_stale("daily", now)
        ):
            return "daily"
        if (
            self.overall_15min
            and self.overall_15min.exhausted()
            and not self._tier_stale("15min", now)
        ):
            return "15min"
        return None

    def cooldown_until_epoch(self, tier: str | None = None, now: float | None = None) -> int:
        """Epoch when the (given or default) exhausted tier next resets."""
        now = self._clock() if now is None else now
        if tier == "daily":
            return next_midnight_utc(now)
        # 15-min window, and the safe fallback for a 429 without usable headers.
        return next_quarter_hour(now)

    def snapshot(self) -> dict[str, object]:
        """Serializable view for ``sync_state`` / ``sync_status``."""

        def as_dict(u: Usage | None) -> dict[str, int] | None:
            return None if u is None else {"used": u.used, "limit": u.limit}

        return {
            "read_15min": as_dict(self.read_15min),
            "read_daily": as_dict(self.read_daily),
            "overall_15min": as_dict(self.overall_15min),
            "overall_daily": as_dict(self.overall_daily),
            "self_limit": self.max_requests,
        }
