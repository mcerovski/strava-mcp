"""Segments syncer: starred segments full detail (encountered come from efforts).

``/segments/starred`` lists the athlete's starred segments; each is upgraded to
a full ``DetailedSegment`` via ``/segments/{id}`` and stored with ``starred=1``.
Encountered segments are written by the enrichment unit (ADR 0001) — never
fetched here.
"""

from __future__ import annotations

from typing import Any, Protocol

from strava_mcp.db.repositories.segments import SegmentsRepository


class _Client(Protocol):
    def get(self, path: str, *, params: dict[str, Any] | None = ...) -> Any: ...


class SegmentsSyncer:
    def __init__(self, client: _Client, repo: SegmentsRepository) -> None:
        self.client = client
        self.repo = repo

    def run_starred(self) -> None:
        starred = self.client.get("/segments/starred") or []
        for summary in starred:
            detail = self.client.get(f"/segments/{summary['id']}")
            self.repo.upsert_starred(detail)
