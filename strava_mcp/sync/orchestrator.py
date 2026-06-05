"""The background worker state machine: BOOTSTRAP → BACKFILL → POLL.

One dedicated thread is the sole DB writer (research R12). The ``Orchestrator``
holds the worker logic and is driven either by tests (call phases directly) or
by ``Worker`` (a real thread). BACKFILL pages newest→oldest, checkpointing the
frontier after every page so a restart resumes with zero re-fetch; on budget
exhaustion or a 429 it cools down deterministically to the next reset
(Constitution IV). POLL is layered in by US7.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from strava_mcp.client.ratelimit import (
    BudgetExhausted,
    RateLimitBudget,
    next_quarter_hour,
)
from strava_mcp.config import Settings
from strava_mcp.db.repositories.activities import ActivitiesRepository, parse_epoch
from strava_mcp.db.repositories.athlete import AthleteRepository
from strava_mcp.db.repositories.gear import GearRepository
from strava_mcp.db.repositories.routes import RoutesRepository
from strava_mcp.db.repositories.segments import SegmentsRepository
from strava_mcp.logging import get_logger
from strava_mcp.sync.resources.activities import ActivitiesSyncer
from strava_mcp.sync.resources.athlete import AthleteSyncer
from strava_mcp.sync.resources.gear import GearSyncer
from strava_mcp.sync.resources.routes import RoutesSyncer
from strava_mcp.sync.resources.segments import SegmentsSyncer
from strava_mcp.sync.state import SyncState

log = get_logger()

POLL_LOOKBACK_SECONDS = 14 * 24 * 3600  # 14-day lookback (ADR 0003)
POLL_INTERVAL_SECONDS = 12 * 3600  # steady-state poll cadence


class _Client(Protocol):
    def get(self, path: str, *, params: dict[str, Any] | None = ...) -> Any: ...


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Orchestrator:
    """Worker logic over a single read/write connection and a Strava client."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        client: _Client,
        settings: Settings,
        *,
        stop_event: threading.Event | None = None,
        poll_event: threading.Event | None = None,
        budget: RateLimitBudget | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        per_page: int = 30,
    ) -> None:
        self.conn = conn
        self.client = client
        self.settings = settings
        self.stop_event = stop_event or threading.Event()
        self.poll_event = poll_event or threading.Event()
        self.budget = budget
        self.clock = clock
        self.sleep = sleep
        self.state = SyncState(conn)
        self.athlete_repo = AthleteRepository(conn)
        self.activities_repo = ActivitiesRepository(conn)
        self.activities_syncer = ActivitiesSyncer(client, self.activities_repo, per_page=per_page)

    # --- phases ------------------------------------------------------------
    def bootstrap(self) -> None:
        """BOOTSTRAP: mirror the athlete, gear, routes, and starred segments."""
        self.state.ensure()
        self.state.set_phase("BOOTSTRAP")
        log.info("BOOTSTRAP: mirroring athlete profile/zones/stats")
        AthleteSyncer(self.client, self.athlete_repo).run()

        profile = (self.athlete_repo.read() or {}).get("profile") or {}
        athlete_id = int(profile.get("id", 0))
        self._run_with_cooldown(
            lambda: GearSyncer(self.client, GearRepository(self.conn)).run(profile),
            label="BOOTSTRAP gear",
        )
        if athlete_id:
            self._run_with_cooldown(
                lambda: RoutesSyncer(self.client, RoutesRepository(self.conn)).run(athlete_id),
                label="BOOTSTRAP routes",
            )
        self._run_with_cooldown(
            lambda: SegmentsSyncer(self.client, SegmentsRepository(self.conn)).run_starred(),
            label="BOOTSTRAP starred segments",
        )
        self.state.append_run_log({"phase": "BOOTSTRAP", "event": "bootstrap_complete"})

    def backfill(self, *, max_pages: int | None = None) -> None:
        """BACKFILL: page summaries newest→oldest, checkpoint after every page.

        Resumes from the stored frontier; on exhaustion/429 it cools down to the
        known next reset and continues. Marks ``backfill_complete`` when paging
        reaches the first-ever activity (an empty page).
        """
        self.state.ensure()
        self.state.set_phase("BACKFILL")
        before = self.state.snapshot().get("backfill_frontier_epoch")
        if before:
            log.info("BACKFILL: resuming from frontier %s", _iso(before))
        else:
            log.info("BACKFILL: starting from the newest activity")
        pages = 0
        while not self.stop_event.is_set():
            if max_pages is not None and pages >= max_pages:
                return
            try:
                summaries = self.activities_syncer.fetch_summaries(before_epoch=before)
            except Exception as exc:  # noqa: BLE001 - re-raised unless rate-limit
                if not self._is_rate_limit(exc):
                    raise
                self._cooldown(exc)
                continue

            if not summaries:
                self.state.mark_backfill_complete()
                self.state.append_run_log({"phase": "BACKFILL", "event": "backfill_complete"})
                log.info("BACKFILL complete: reached first-ever activity")
                return

            oldest = self.activities_syncer.store_summaries(summaries)
            self._enrich_page(summaries)
            if oldest is not None:
                before = oldest
                self.state.set_frontier(oldest)  # checkpoint after every page
            if self.budget is not None:
                self.state.set_rate_limit(self.budget.snapshot())
            pages += 1
            log.info(
                "BACKFILL: stored %d summaries, frontier=%s",
                len(summaries),
                _iso(before) if before else "n/a",
            )

    def _enrich_page(self, summaries: list[dict[str, Any]]) -> None:
        """Enrich each activity in a page as a single visible unit (US4).

        Activities already enriched (e.g. from a page re-fetched after a restart)
        are skipped — no re-fetch — so resume is effectively zero-cost beyond the
        summary listing. Each newly-enriched activity is logged for visibility.
        """
        total = len(summaries)
        for index, summary in enumerate(summaries, start=1):
            if self.stop_event.is_set():
                return
            activity_id = int(summary["id"])
            if self.activities_repo.status(activity_id) == "enriched":
                continue  # already enriched on a previous run — skip, no re-fetch
            self._enrich_one(activity_id)
            if self.activities_repo.status(activity_id) == "enriched":
                date = (summary.get("start_date") or "?")[:10]
                log.info(
                    "enriched activity %s (%s) — %d/%d this page",
                    activity_id,
                    date,
                    index,
                    total,
                )

    def _enrich_one(self, activity_id: int) -> None:
        """Enrich one activity, cooling down and retrying on rate limits.

        A non-rate-limit failure leaves the activity ``not_yet_synced`` (never
        partially visible) rather than aborting the backfill.
        """
        self._run_with_cooldown(
            lambda: self.activities_syncer.enrich(activity_id),
            label=f"enrichment activity {activity_id}",
        )

    def _run_with_cooldown(self, fn: Callable[[], None], *, label: str) -> None:
        """Run ``fn``, cooling down + retrying on rate limits; log-and-skip otherwise."""
        while not self.stop_event.is_set():
            try:
                fn()
                return
            except Exception as exc:  # noqa: BLE001 - retried or logged-and-skipped
                if self._is_rate_limit(exc):
                    self._cooldown(exc)
                    continue
                log.warning("%s failed: %s", label, exc)
                return

    # --- poll (US7) --------------------------------------------------------
    def poll(self) -> list[int]:
        """POLL: capture new activities (insert-only, 14-day lookback, dedupe).

        Lists ``after = newest_synced − 14d``, enriches and inserts only ids not
        already stored, and advances ``newest_synced``. Existing rows are never
        mutated (ADR 0003), so a back-dated upload within the window is captured.
        """
        self.state.ensure()
        self.state.set_phase("POLL")
        snap = self.state.snapshot()
        newest = snap.get("newest_synced_epoch")
        after = max(0, newest - POLL_LOOKBACK_SECONDS) if newest else None

        try:
            summaries = self.activities_syncer.fetch_summaries(after_epoch=after, per_page=200)
        except Exception as exc:  # noqa: BLE001
            if not self._is_rate_limit(exc):
                raise
            self._cooldown(exc)
            summaries = self.activities_syncer.fetch_summaries(after_epoch=after, per_page=200)

        inserted: list[int] = []
        new_newest = newest or 0
        for summary in summaries:
            activity_id = int(summary["id"])
            if self.activities_repo.status(activity_id) != "absent":
                continue  # dedupe-by-id: already stored, never mutate (insert-only)
            self.activities_repo.insert_summary(summary)
            self._enrich_one(activity_id)
            if self.activities_repo.status(activity_id) == "enriched":
                inserted.append(activity_id)
                epoch = parse_epoch(summary.get("start_date"))
                if epoch is not None and epoch > new_newest:
                    new_newest = epoch

        if new_newest:
            self.state.set_newest_synced(new_newest)
        self.state.set_last_poll(_iso(int(self.clock())))
        outcome = f"inserted {len(inserted)} new activities" if inserted else "no new activities"
        self.state.append_run_log(
            {"phase": "POLL", "event": "poll", "inserted": inserted, "outcome": outcome}
        )
        log.info("POLL: %s", outcome)
        return inserted

    # --- cooldown ----------------------------------------------------------
    @staticmethod
    def _is_rate_limit(exc: BaseException) -> bool:
        from strava_mcp.client.http import RateLimitExceeded

        return isinstance(exc, (BudgetExhausted, RateLimitExceeded))

    def _budget_summary(self) -> str:
        """Human-readable read-budget usage for cooldown logs (or empty)."""
        if self.budget is None:
            return ""
        parts: list[str] = []
        if self.budget.read_15min is not None:
            u = self.budget.read_15min
            parts.append(f"read {u.used}/{u.limit} (15min)")
        if self.budget.read_daily is not None:
            u = self.budget.read_daily
            parts.append(f"{u.used}/{u.limit} (daily)")
        return f" [{', '.join(parts)}]" if parts else ""

    def _cooldown(self, exc: BaseException) -> None:
        tier = getattr(exc, "tier", None)
        if self.budget is not None:
            target = self.budget.cooldown_until_epoch(tier)
        else:
            target = next_quarter_hour(self.clock())
        until = _iso(target)
        self.state.set_phase("COOLDOWN")
        self.state.set_cooldown(until)
        if self.budget is not None:
            # Persist the budget snapshot so sync_status reflects it during cooldown.
            self.state.set_rate_limit(self.budget.snapshot())
        self.state.append_run_log({"phase": "COOLDOWN", "until": until, "tier": tier})
        log.info("COOLDOWN until %s (tier=%s)%s", until, tier, self._budget_summary())
        self._sleep_until(target)
        self.state.set_cooldown(None)
        self.state.set_phase("BACKFILL")

    def _sleep_until(self, target_epoch: int) -> None:
        while not self.stop_event.is_set() and self.clock() < target_epoch:
            remaining = target_epoch - self.clock()
            self.sleep(min(remaining, 60.0))

    # --- run loops ---------------------------------------------------------
    def run_once(self) -> None:
        """Run a single bootstrap+backfill pass (used in tests)."""
        self.bootstrap()
        self.backfill()

    def run_forever(self) -> None:
        """Drive the worker until ``stop_event`` is set.

        After BOOTSTRAP + BACKFILL, the worker enters the steady-state POLL loop:
        poll every 12h, or immediately when ``sync_now`` fires ``poll_event``.
        """
        self.bootstrap()
        self.backfill()
        while not self.stop_event.is_set():
            self.poll()
            # Wait up to the poll interval, but wake early on a sync_now nudge.
            self.poll_event.wait(timeout=POLL_INTERVAL_SECONDS)
            self.poll_event.clear()


class Worker(threading.Thread):
    """Owns its own connection + client and runs the orchestrator in a thread."""

    def __init__(self, settings: Settings, *, stop_event: threading.Event) -> None:
        super().__init__(name="strava-sync-worker", daemon=True)
        self.settings = settings
        self.stop_event = stop_event
        # Set by sync_now to nudge an immediate POLL.
        self.poll_event = threading.Event()

    def run(self) -> None:
        from strava_mcp.auth.tokens import TokenStore
        from strava_mcp.client.http import StravaClient
        from strava_mcp.db import engine

        conn = engine.connect(self.settings.strava_db_path)
        try:
            store = TokenStore(conn, self.settings)
            budget = RateLimitBudget(max_requests=self.settings.sync_max_requests)
            client = StravaClient(store.access_token, rate_limiter=budget)
            orchestrator = Orchestrator(
                conn,
                client,
                self.settings,
                stop_event=self.stop_event,
                poll_event=self.poll_event,
                budget=budget,
            )
            try:
                orchestrator.run_forever()
            finally:
                client.close()
        except Exception:  # pragma: no cover - defensive worker guard
            log.exception("worker thread crashed")
        finally:
            conn.close()
