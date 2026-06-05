"""Shared pytest fixtures: a temp WAL SQLite database and an injectable clock.

No test contacts the live Strava API (Constitution II). DB tests run against a
real temporary SQLite file in WAL mode — not mocks.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from strava_mcp.db import engine


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Path to a fresh SQLite DB file inside the test's temp dir."""
    return tmp_path / "strava.db"


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    """A bootstrapped read/write connection (WAL, schema applied)."""
    connection = engine.connect(db_path)
    try:
        yield connection
    finally:
        connection.close()


class FakeClock:
    """A controllable clock for deterministic time-based tests."""

    def __init__(self, epoch: float) -> None:
        self._epoch = epoch

    def time(self) -> float:
        return self._epoch

    def advance(self, seconds: float) -> None:
        self._epoch += seconds

    def set(self, epoch: float) -> None:
        self._epoch = epoch


@pytest.fixture
def clock() -> FakeClock:
    """Injectable clock pinned to a fixed instant (2021-06-01T12:00:00Z)."""
    # 2021-06-01T12:00:00Z = 1622548800
    return FakeClock(1622548800.0)


@pytest.fixture
def now_fn(clock: FakeClock) -> Callable[[], float]:
    return clock.time


class FakeStravaClient:
    """Offline stand-in for the Strava HTTP client.

    Routes each ``get(path, params)`` through a caller-supplied handler so tests
    drive syncers with recorded fixtures and never touch the live API
    (Constitution II). Records every call for assertions.
    """

    def __init__(self, handler: Callable[[str, dict[str, object]], object]) -> None:
        self._handler = handler
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, path: str, *, params: dict[str, object] | None = None) -> object:
        p = dict(params or {})
        self.calls.append((path, p))
        return self._handler(path, p)

    def close(self) -> None:
        pass


def _epoch(start_date: str | None) -> int:
    from strava_mcp.db.repositories.activities import parse_epoch

    return parse_epoch(start_date) or 0


_DEFAULT_STREAMS = {
    "time": {
        "data": [0, 1, 2],
        "series_type": "distance",
        "original_size": 3,
        "resolution": "high",
    },
    "heartrate": {
        "data": [120, 130, 140],
        "series_type": "distance",
        "original_size": 3,
        "resolution": "high",
    },
}


def build_handler(
    summaries: list[dict[str, Any]],
    *,
    details: dict[int, dict[str, Any]] | None = None,
    facets: dict[int, dict[str, list[Any]]] | None = None,
    streams: dict[str, Any] | None = None,
    per_page: int = 30,
) -> Callable[[str, dict[str, Any]], Any]:
    """Build a handler serving paged summaries + per-activity enrichment.

    ``/athlete/activities`` is paged newest→oldest via ``before``. Enrichment
    endpoints (``/activities/{id}``, ``/laps``, ``/comments``, ``/kudos``,
    ``/zones``, ``/streams``) return the supplied data or sensible empties so the
    enrichment unit always succeeds (streams default to a tiny non-empty set).
    """
    details = details or {}
    facets = facets or {}
    default_streams = _DEFAULT_STREAMS if streams is None else streams
    by_id = {int(a["id"]): a for a in summaries}

    def handler(path: str, params: dict[str, Any]) -> Any:
        if path == "/athlete/activities":
            items = sorted(summaries, key=lambda a: _epoch(a.get("start_date")), reverse=True)
            before = params.get("before")
            if before is not None:
                items = [a for a in items if _epoch(a.get("start_date")) < before]
            return items[: int(params.get("per_page", per_page))]

        parts = path.strip("/").split("/")
        if parts[0] == "activities":
            aid = int(parts[1])
            if len(parts) == 2:
                return details.get(aid, by_id.get(aid, {"id": aid}))
            sub = parts[2]
            if sub == "streams":
                return default_streams
            return facets.get(aid, {}).get(sub, [])

        raise AssertionError(f"unexpected path: {path}")

    return handler
