"""T018 [US2] BOOTSTRAP fetches athlete profile+zones+stats and dual-writes."""

from __future__ import annotations

import json
import sqlite3

from strava_mcp.config import Settings
from strava_mcp.sync.orchestrator import Orchestrator

from tests.conftest import FakeStravaClient
from tests.fixtures import load


def _handler(path: str, params: dict[str, object]) -> object:
    if path == "/athlete":
        return load("athlete")
    if path == "/athlete/zones":
        return load("athlete_zones")
    if path.startswith("/athletes/") and path.endswith("/stats"):
        return load("athlete_stats")
    # Extended BOOTSTRAP (US6) also fetches gear/routes/starred segments.
    if path.startswith("/gear/"):
        return {"id": path.rsplit("/", 1)[-1], "name": "Gear"}
    if path.endswith("/routes"):
        return []
    if path == "/segments/starred":
        return []
    raise AssertionError(f"unexpected path: {path}")


def _settings() -> Settings:
    return Settings(strava_client_id="c", strava_client_secret="s", _env_file=None)


def test_bootstrap_dual_writes_athlete(conn: sqlite3.Connection) -> None:
    client = FakeStravaClient(_handler)
    orch = Orchestrator(conn, client, _settings())
    orch.bootstrap()

    # Normalized athlete row populated.
    row = conn.execute(
        "SELECT id, username, firstname, detail_json, zones_json, stats_json FROM athlete"
    ).fetchone()
    assert row["id"] == 12345
    assert row["username"] == "athlete_one"
    assert json.loads(row["detail_json"])["id"] == 12345
    assert json.loads(row["zones_json"])["heart_rate"]["zones"]
    assert json.loads(row["stats_json"])["all_ride_totals"]["count"] == 500

    # Dual-write: a raw_responses row exists for each fetched facet.
    raw_types = {
        r["resource_type"]
        for r in conn.execute("SELECT resource_type FROM raw_responses").fetchall()
    }
    assert {"athlete", "athlete_zones", "athlete_stats"} <= raw_types

    # Phase recorded.
    assert (
        conn.execute("SELECT phase FROM sync_state WHERE id=1").fetchone()["phase"] == "BOOTSTRAP"
    )


def test_bootstrap_calls_expected_endpoints(conn: sqlite3.Connection) -> None:
    client = FakeStravaClient(_handler)
    Orchestrator(conn, client, _settings()).bootstrap()
    paths = [c[0] for c in client.calls]
    # Athlete is fetched first, in order, before the other BOOTSTRAP resources.
    assert paths[:3] == ["/athlete", "/athlete/zones", "/athletes/12345/stats"]
    # Gear ids come from the athlete profile's bikes/shoes.
    assert "/gear/b1234" in paths and "/gear/g5678" in paths
    assert "/segments/starred" in paths
