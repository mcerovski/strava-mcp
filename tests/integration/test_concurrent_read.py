"""T073 A tool read succeeds concurrently with the worker writing under WAL.

Closes spec Edge Case "Concurrent agent reads during backfill": under WAL the
single writer and read-only readers never block each other.
"""

from __future__ import annotations

import threading
from pathlib import Path

from strava_mcp.db import engine
from strava_mcp.db.repositories.activities import ActivitiesRepository
from strava_mcp.mcp.tools.sync import sync_status


def test_reads_succeed_while_worker_writes(db_path: Path) -> None:
    writer = engine.connect(db_path)
    repo = ActivitiesRepository(writer)

    errors: list[Exception] = []
    counts: list[int] = []
    stop = threading.Event()

    def write_loop() -> None:
        try:
            for i in range(200):
                repo.insert_summary(
                    {"id": i, "start_date": "2021-05-01T00:00:00Z", "sport_type": "Ride"}
                )
                writer.execute("UPDATE activities SET enriched_at = ? WHERE id = ?", ("x", i))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            stop.set()

    def read_loop() -> None:
        try:
            while not stop.is_set():
                # A pure read-only tool call against the same DB file.
                status = sync_status(db_path)
                counts.append(status["counts"]["activities"])
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    t_write = threading.Thread(target=write_loop)
    t_read = threading.Thread(target=read_loop)
    t_read.start()
    t_write.start()
    t_write.join(timeout=10)
    t_read.join(timeout=10)
    writer.close()

    assert not errors, f"concurrent read/write raised: {errors}"
    assert counts, "reader never completed a read"
    # The final read-only count reflects all committed writes (no blocking/loss).
    assert sync_status(db_path)["counts"]["activities"] == 200
