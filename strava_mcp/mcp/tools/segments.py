"""Segment read tools (US6): list_starred_segments / get_segment / list_segment_efforts.

``get_segment`` returns the full ``DetailedSegment`` for a starred segment and
the embedded ``SummarySegment`` for an encountered one — never a live fetch
(ADR 0001).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strava_mcp.db.repositories.segments import SegmentsRepository
from strava_mcp.mcp.tools import not_found, reader


def list_starred_segments(db_path: Path | str) -> list[dict[str, Any]]:
    with reader(db_path) as conn:
        return SegmentsRepository(conn).list_starred()


def get_segment(db_path: Path | str, segment_id: int) -> dict[str, Any]:
    with reader(db_path) as conn:
        segment = SegmentsRepository(conn).get(segment_id)
    return segment if segment is not None else not_found(segment_id)


def list_segment_efforts(db_path: Path | str, segment_id: int) -> list[dict[str, Any]]:
    with reader(db_path) as conn:
        return SegmentsRepository(conn).efforts_for_segment(segment_id)
