"""Activities syncer: page summaries newest→oldest (US3); enrich a unit (US4).

Backfill paging uses ``before=<frontier_epoch>`` so a restart resumes strictly
older than the checkpoint with zero re-fetch (Constitution IV). The enrichment
unit (detail + laps + zones + streams + efforts, stamped
``enriched_at`` last) is added in US4 (T039).
"""

from __future__ import annotations

from typing import Any, Protocol

from strava_mcp.db.repositories.activities import ActivitiesRepository, parse_epoch

# Stream types pursued at enrichment (research R7).
STREAM_KEYS = (
    "time,distance,latlng,altitude,velocity_smooth,heartrate,cadence,watts,temp,moving,grade_smooth"
)


class _Client(Protocol):
    def get(self, path: str, *, params: dict[str, Any] | None = ...) -> Any: ...


class ActivitiesSyncer:
    def __init__(
        self,
        client: _Client,
        repo: ActivitiesRepository,
        *,
        per_page: int = 30,
    ) -> None:
        self.client = client
        self.repo = repo
        self.per_page = per_page

    def fetch_summaries(
        self,
        *,
        before_epoch: int | None = None,
        after_epoch: int | None = None,
        per_page: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch one page of activity summaries.

        ``before`` bounds the backfill sweep to activities older than the frontier
        (so resume never re-fetches); ``after`` bounds the POLL to the lookback
        window (newest_synced − 14d).
        """
        params: dict[str, Any] = {"per_page": per_page or self.per_page}
        if before_epoch is not None:
            params["before"] = before_epoch
        if after_epoch is not None:
            params["after"] = after_epoch
        page = self.client.get("/athlete/activities", params=params)
        return list(page or [])

    def store_summaries(self, summaries: list[dict[str, Any]]) -> int | None:
        """Insert each summary (insert-only); return the oldest epoch in the page."""
        oldest: int | None = None
        for summary in summaries:
            self.repo.insert_summary(summary)
            epoch = parse_epoch(summary.get("start_date"))
            if epoch is not None and (oldest is None or epoch < oldest):
                oldest = epoch
        return oldest

    # --- enrichment unit (US4) --------------------------------------------
    def enrich(self, activity_id: int) -> None:
        """Fetch the full enrichment unit (incl. streams) and write it atomically.

        Streams are fetched and persisted as part of the unit; the repository
        stamps ``enriched_at`` only after they are stored (visibility invariant).
        Rate-limit errors propagate so the worker can cool down and retry.
        """
        detail = self.client.get(f"/activities/{activity_id}")
        laps = self._safe_list(f"/activities/{activity_id}/laps")
        zones = self._safe_list(f"/activities/{activity_id}/zones")
        streams = (
            self.client.get(
                f"/activities/{activity_id}/streams",
                params={"keys": STREAM_KEYS, "key_by_type": "true"},
            )
            or {}
        )
        self.repo.enrich(
            detail=detail,
            laps=laps,
            zones=zones,
            streams=streams,
        )

    def _safe_list(self, path: str) -> list[dict[str, Any]]:
        """Fetch an optional facet list; swallow not-found, propagate rate limits."""
        from strava_mcp.client.http import RateLimitExceeded, StravaError

        try:
            return list(self.client.get(path) or [])
        except RateLimitExceeded:
            raise
        except StravaError:
            return []
