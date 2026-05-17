"""ReactivityRunner — single async loop that polls the ledger and dispatches.

The Runner is the "outer loop" of every reactivity. It reads new ledger
entries since its cursor, hands each one to the registry's ``dispatch``,
and sleeps. Cancel-safe; tenant-reset-safe (rewinds cursor on detected
wipe + re-seed).

Architectural fit: this is the same shape as ``ProjectionRunner`` and the
existing one-off reactivity loops (``identity_discovery`` poller,
``process_extractor`` poller, ``chat_received_reactivity_poller``). The
gain is uniformity — once a Reactivity is registered into the registry,
the Runner picks it up automatically. New reactivities don't need a new
loop.

Tenant-reset detection follows the projection_runner pattern:

    rows = ledger.fetch(company_id)
    if no rows: rewind (someone wiped the ledger)
    elif max_seq < cursor: rewind (smaller max → wipe-and-re-seed)
    elif row at cursor has different hash: rewind (same-seq wipe-and-re-seed)
    else: process new rows since cursor

We don't carry the ``_last_hash`` state from projection_runner because
the registry is idempotent at the action level: re-firing a reactivity
on the same entry would write a second ``emit_reactivity_fired`` row,
which the dashboard surfaces as "fired twice" — visible, not silent. A
future wave can add per-(reactivity, source_seq) dedup if customers
report noise.

Poll interval defaults to 1s — reactivities are latency-sensitive
(statement-to-owner DMs should land within seconds of the statement).
Override via env ``WORM_CORE_REACTIVITY_INTERVAL_S``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from uuid import UUID

from wormbase_reactivities.registry import ReactivityRegistry

logger = logging.getLogger("wormbase_reactivities.runner")

_DEFAULT_INTERVAL_ENV = "WORM_CORE_REACTIVITY_INTERVAL_S"


def _default_interval_s() -> float:
    """Pick the poll interval from env, defaulting to 1s.

    1s is aggressive vs the 30s identity_discovery default — but
    reactivity DMs are user-visible. Tests can lower this via the
    env var or the constructor.
    """
    raw = os.environ.get(_DEFAULT_INTERVAL_ENV)
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return 1.0


class ReactivityRunner:
    """Polls the ledger; dispatches new entries through the registry.

    Single-tenant, single-loop. Construct with a registry already
    populated with bindings; ``run_forever()`` is the entry point.

    The runner does NOT touch the registry's binding list — registration
    is a startup concern. The runner only calls ``registry.dispatch(entry)``
    per new ledger row.
    """

    def __init__(
        self,
        ledger: Any,
        company_id: UUID,
        registry: ReactivityRegistry,
        *,
        poll_interval_s: float | None = None,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        self._registry = registry
        self._poll_interval_s = (
            poll_interval_s
            if poll_interval_s is not None
            else _default_interval_s()
        )
        self._last_seq: int = 0
        # ``_last_hash`` follows the same pattern as
        # ``ProjectionRunner._last_hash`` — detect wipe-and-re-seed that
        # lands on the same seq counter (ledger reset that produces an
        # identical max_seq but a different hash chain).
        self._last_hash: bytes | None = None

    @property
    def last_seq(self) -> int:
        return self._last_seq

    async def run_forever(self) -> None:
        """Periodic loop. Cancel-safe."""
        logger.info(
            "reactivity_runner starting: company_id=%s interval=%.2fs",
            self._company_id, self._poll_interval_s,
        )
        while True:
            try:
                fired = await self.run_once()
                if fired:
                    logger.info(
                        "reactivity_runner: fired %d reactivit%s",
                        fired, "y" if fired == 1 else "ies",
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("reactivity_runner cycle failed: %s", exc)
            try:
                await asyncio.sleep(self._poll_interval_s)
            except asyncio.CancelledError:
                raise

    async def run_once(self) -> int:
        """One pass: fetch new entries, dispatch each, advance cursor.

        Returns the count of (reactivity_id, entry) pairs that fired
        this cycle. 0 means either no new entries or no matches.
        """
        rows = await self._ledger.fetch(self._company_id)
        if not rows:
            # Empty ledger: tenant was wiped or never had entries.
            if self._last_seq != 0:
                logger.info(
                    "reactivity_runner: tenant reset detected (rows empty), "
                    "rewinding cursor company_id=%s prev_seq=%d",
                    self._company_id, self._last_seq,
                )
                self._last_seq = 0
                self._last_hash = None
            return 0

        rows_sorted = sorted(rows, key=lambda r: int(r.get("seq", 0)))
        max_seq = int(rows_sorted[-1].get("seq", 0))

        # Tenant-reset: ledger went smaller than our cursor.
        reset_detected = False
        if max_seq < self._last_seq:
            logger.info(
                "reactivity_runner: tenant reset detected (max=%d < cursor=%d), "
                "rewinding company_id=%s",
                max_seq, self._last_seq, self._company_id,
            )
            reset_detected = True
        elif self._last_seq > 0 and self._last_hash is not None:
            cursor_row = next(
                (r for r in rows_sorted if int(r.get("seq", 0)) == self._last_seq),
                None,
            )
            if cursor_row is not None and cursor_row.get("hash") != self._last_hash:
                logger.info(
                    "reactivity_runner: tenant reset detected "
                    "(hash mismatch at seq=%d), rewinding company_id=%s",
                    self._last_seq, self._company_id,
                )
                reset_detected = True

        if reset_detected:
            self._last_seq = 0
            self._last_hash = None

        # Walk only new rows. The registry's writes from this dispatch
        # advance the ledger's seq counter, but we computed ``max_seq``
        # before dispatching, so they fall outside the cycle.
        cycle_cursor = self._last_seq
        fire_total = 0
        for r in rows_sorted:
            seq = int(r.get("seq", 0))
            if seq <= cycle_cursor:
                continue
            fired_ids = await self._registry.dispatch(r)
            fire_total += len(fired_ids)

        # Advance the cursor + remember the tail hash for next-pass
        # wipe-detection. We refetch max_seq via rows because dispatch
        # itself may have written; we want the post-cycle tail.
        post_rows = await self._ledger.fetch(self._company_id)
        if post_rows:
            post_sorted = sorted(post_rows, key=lambda r: int(r.get("seq", 0)))
            self._last_seq = int(post_sorted[-1].get("seq", 0))
            self._last_hash = post_sorted[-1].get("hash")
        return fire_total


__all__ = ["ReactivityRunner"]
