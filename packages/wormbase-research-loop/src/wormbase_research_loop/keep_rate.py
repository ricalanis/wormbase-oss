"""``keep_rate`` — nightly keep-rate publisher (Demo-day P1).

Wave C₁ Block D.1 — verbatim lift of
``apps/worm-core/src/wormbase_core/keep_rate_publisher.py`` into the
research-loop package. Logger renamed to
``wormbase_research_loop.keep_rate``; behaviour unchanged. Block F.4
wraps the ``KeepRatePublisher`` class as a Reactivity to close the
live wiring gap (the publisher was previously unwired in cli/service
per the Wave C₁ spike).

Computes per-scope keep-rate over the trailing day for a tenant and
appends one ``metrics_keep_rate_published`` ledger entry per scope.
The job is **idempotent**: running twice for the same (scope, day)
tuple is a no-op (the publisher dedupes by inspecting prior published
entries before writing).

Wraps each write in the canonical PEVR cycle so the publication is
hash-chained, replayable, and audit-complete. Per CLAUDE.md
invariant 7 (auditable governance), the entry carries
``published_by`` and ``published_at`` distinct from the
``day``-window anchor.

Cron wiring lives in ``apps/worm-core/src/wormbase_core/cli.py`` as a
new reactivity task; in dev the loop ticks every 5 minutes (so a demo
arc can produce visible publications during a 60-second install). In
production the loop ticks once per hour and the dedup logic prevents
duplicate publications.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import MetricsKeepRatePublishedPayload

from wormbase_core.projections.keep_rate import (
    keep_rate_for_window,
)

logger = logging.getLogger("wormbase_research_loop.keep_rate")

# Type alias — anything with the canonical async ``write/fetch`` surface works.
LedgerLike = Ledger | InMemoryLedger | Any


def _default_interval_s() -> float:
    """Pick the publish interval from env, with dev/prod-flavoured defaults."""
    raw = os.environ.get("WORM_CORE_KEEP_RATE_INTERVAL_S")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    is_dev = os.environ.get("WORMBASE_DEV", "").strip().lower() in ("1", "true")
    return 300.0 if is_dev else 3600.0  # 5 min dev, 1 h prod


async def _already_published(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    scope: str,
    day: str,
) -> bool:
    """Idempotency check: has (scope, day) already been published?

    Inspects all ``execute`` rows whose tool is
    ``emit_metrics_keep_rate_published`` and matches both args. Cheap
    enough at single-tenant scale that we skip a memo cache; the
    publisher only fires once per day per scope in steady state.
    """
    rows = await ledger.fetch(company_id)
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload", {})
        if payload.get("tool") != "emit_metrics_keep_rate_published":
            continue
        args = payload.get("args", {}) or {}
        if args.get("scope") == scope and args.get("day") == day:
            return True
    return False


async def publish_for_day(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    day: date | None = None,
    published_by: str = "worm",
    scopes: tuple[str, ...] = ("person", "team", "company"),
) -> list[MetricsKeepRatePublishedPayload]:
    """Publish keep-rate for ``day`` (defaults to yesterday UTC).

    Returns the list of payloads that were *newly* published. If a
    (scope, day) was already published the job skips it (idempotent).
    """
    target_day = day or (datetime.now(UTC) - timedelta(days=1)).date()
    rows = await ledger.fetch(company_id)
    keep_rate_rows = keep_rate_for_window(rows, day=target_day, scopes=scopes)

    published: list[MetricsKeepRatePublishedPayload] = []
    for kr in keep_rate_rows:
        if await _already_published(
            ledger, company_id, scope=kr.scope, day=kr.day,
        ):
            logger.debug(
                "skip already-published scope=%s day=%s", kr.scope, kr.day,
            )
            continue
        payload = MetricsKeepRatePublishedPayload(
            scope=kr.scope,
            day=kr.day,
            kept=kr.kept,
            total=kr.total,
            ratio=kr.ratio,
            published_by=published_by,
            published_at=datetime.now(UTC),
        )
        await _emit_publication(
            ledger, company_id, payload=payload, published_by=published_by,
        )
        published.append(payload)
    return published


async def _emit_publication(
    ledger: LedgerLike,
    company_id: UUID,
    *,
    payload: MetricsKeepRatePublishedPayload,
    published_by: str,
) -> None:
    """Wrap a single publication in the canonical PEVR cycle."""
    args = payload.model_dump(mode="json")
    ref_id = uuid4()  # synthetic ref_id — the entry's natural key is (scope, day)

    def _verify(_exec_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            MetricsKeepRatePublishedPayload(**args)
            return {
                "checks": [{"name": "metrics_keep_rate_payload_valid", "ok": True}],
                "passed": True,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "checks": [
                    {
                        "name": "metrics_keep_rate_payload_valid",
                        "ok": False,
                        "error": str(exc),
                    }
                ],
                "passed": False,
            }

    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "metrics_keep_rate_published",
            "ref_id": str(ref_id),
            "reason": (
                f"keep-rate publication scope={payload.scope} day={payload.day}"
            ),
            "proposed_by": published_by,
        },
        execute_fn=lambda: {
            "tool": "emit_metrics_keep_rate_published",
            "args": args,
            "result_ref": f"{payload.scope}:{payload.day}",
        },
        verify_fn=_verify,
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "keep-rate published per nightly cadence",
        },
        quadrant="passive_deterministic",
    )


# ---------------------------------------------------------------------------
# Long-lived loop runner
# ---------------------------------------------------------------------------


class KeepRatePublisher:
    """Async loop that publishes per-scope keep-rate on a fixed interval."""

    def __init__(
        self,
        ledger: LedgerLike,
        company_id: UUID,
        *,
        poll_interval_s: float | None = None,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        self._poll_interval_s = (
            poll_interval_s
            if poll_interval_s is not None
            else _default_interval_s()
        )
        self._stop = asyncio.Event()

    async def run(self) -> None:
        """Run forever, publishing once per interval."""
        while not self._stop.is_set():
            try:
                published = await self.publish_for_day()
                if published:
                    logger.info(
                        "published keep-rate scopes=%s day=%s",
                        [p.scope for p in published],
                        published[0].day if published else None,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("keep_rate_publisher loop error")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._poll_interval_s,
                )
            except asyncio.TimeoutError:
                pass

    async def publish_for_day(
        self,
        day: date | None = None,
        *,
        published_by: str = "worm",
        scopes: tuple[str, ...] = ("person", "team", "company"),
    ) -> list[MetricsKeepRatePublishedPayload]:
        """Publish keep-rate for ``day`` (defaults to yesterday UTC).

        Method form of the module-level ``publish_for_day`` so the F.4
        Reactivity can hold a ``KeepRatePublisher`` instance and delegate
        to it without re-passing ``ledger`` / ``company_id``. Returns the
        list of payloads newly published; idempotent across invocations.
        """
        return await publish_for_day(
            self._ledger, self._company_id,
            day=day, published_by=published_by, scopes=scopes,
        )

    def stop(self) -> None:
        self._stop.set()


__all__ = [
    "KeepRatePublisher",
    "publish_for_day",
]
