"""T026 [US3] Rate-limit header parsing + deterministic cooldown math."""

from __future__ import annotations

from datetime import UTC, datetime

from strava_mcp.client.ratelimit import (
    BudgetExhausted,
    RateLimitBudget,
    next_midnight_utc,
    next_quarter_hour,
)


def _epoch(y: int, mo: int, d: int, h: int, mi: int, s: int = 0) -> int:
    return int(datetime(y, mo, d, h, mi, s, tzinfo=UTC).timestamp())


def test_parses_read_tier_headers() -> None:
    budget = RateLimitBudget()
    budget.record(
        {
            "X-ReadRateLimit-Usage": "40,500",
            "X-ReadRateLimit-Limit": "100,1000",
            "X-RateLimit-Usage": "55,600",
            "X-RateLimit-Limit": "200,2000",
        }
    )
    assert budget.read_15min.used == 40 and budget.read_15min.limit == 100
    assert budget.read_daily.used == 500 and budget.read_daily.limit == 1000
    assert budget.overall_15min.used == 55


def test_exhausted_15min_tier_detected() -> None:
    budget = RateLimitBudget()
    budget.record({"X-ReadRateLimit-Usage": "100,500", "X-ReadRateLimit-Limit": "100,1000"})
    assert budget.exhausted_tier() == "15min"


def test_daily_self_limit_below_api_limit() -> None:
    budget = RateLimitBudget(max_requests=900)
    budget.record({"X-ReadRateLimit-Usage": "10,900", "X-ReadRateLimit-Limit": "100,1000"})
    # Under the API daily limit (1000) but at the self-imposed ceiling (900).
    assert budget.exhausted_tier() == "daily"


def test_before_request_raises_when_exhausted() -> None:
    budget = RateLimitBudget()
    budget.record({"X-ReadRateLimit-Usage": "100,100", "X-ReadRateLimit-Limit": "100,1000"})
    try:
        budget.before_request()
    except BudgetExhausted as exc:
        assert exc.tier == "15min"
    else:  # pragma: no cover
        raise AssertionError("expected BudgetExhausted")


def test_exhaustion_clears_after_window_rolls_over() -> None:
    # Regression: after a cooldown the worker must resume, not re-cool on the
    # pre-reset usage counts.
    now = {"t": float(_epoch(2026, 6, 5, 7, 29, 45))}
    budget = RateLimitBudget(clock=lambda: now["t"])
    budget.record({"X-ReadRateLimit-Usage": "100,200", "X-ReadRateLimit-Limit": "100,1000"})
    assert budget.exhausted_tier() == "15min"  # genuinely exhausted in this window

    # Advance the clock past the next quarter-hour boundary (07:30:00).
    now["t"] = float(_epoch(2026, 6, 5, 7, 30, 1))
    # The stale 100/100 reading no longer blocks — the window has reset.
    assert budget.exhausted_tier() is None
    budget.before_request()  # must not raise


def test_daily_exhaustion_clears_after_midnight() -> None:
    now = {"t": float(_epoch(2026, 6, 5, 23, 0))}
    budget = RateLimitBudget(max_requests=900, clock=lambda: now["t"])
    budget.record({"X-ReadRateLimit-Usage": "10,900", "X-ReadRateLimit-Limit": "100,1000"})
    assert budget.exhausted_tier() == "daily"

    now["t"] = float(_epoch(2026, 6, 6, 0, 0, 5))  # past midnight UTC
    assert budget.exhausted_tier() is None


def test_next_quarter_hour_boundaries() -> None:
    assert next_quarter_hour(_epoch(2021, 6, 1, 12, 7)) == _epoch(2021, 6, 1, 12, 15)
    assert next_quarter_hour(_epoch(2021, 6, 1, 12, 50)) == _epoch(2021, 6, 1, 13, 0)
    # Exactly on a boundary → the *next* boundary (window already reset).
    assert next_quarter_hour(_epoch(2021, 6, 1, 12, 15)) == _epoch(2021, 6, 1, 12, 30)


def test_next_midnight_utc() -> None:
    assert next_midnight_utc(_epoch(2021, 6, 1, 23, 50)) == _epoch(2021, 6, 2, 0, 0)
    assert next_midnight_utc(_epoch(2021, 6, 1, 0, 1)) == _epoch(2021, 6, 2, 0, 0)


def test_cooldown_picks_window_per_tier() -> None:
    now = _epoch(2021, 6, 1, 12, 7)
    budget = RateLimitBudget(clock=lambda: now)
    assert budget.cooldown_until_epoch("15min") == _epoch(2021, 6, 1, 12, 15)
    assert budget.cooldown_until_epoch("daily") == _epoch(2021, 6, 2, 0, 0)
    # Unknown tier / 429-without-headers → next quarter-hour fallback.
    assert budget.cooldown_until_epoch(None) == _epoch(2021, 6, 1, 12, 15)
