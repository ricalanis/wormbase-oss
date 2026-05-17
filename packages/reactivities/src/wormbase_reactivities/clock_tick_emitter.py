"""ClockTickEmitter — periodic tick daemon for time-based Reactivities.

v2.B Phase 3 (2026-05-12). Single-tenant clock-tick daemon, parallel
sibling to :class:`wormbase_reactivities.runner.ReactivityRunner`.

Writes one ``clock_tick`` ledger entry every ``tick_interval_s`` seconds.
Each tick advances ``sequence_number`` monotonically per company per
cadence. The emitter does NOT advance the ReactivityRunner's cursor —
the runner picks up the tick like any other entry on its next poll
cycle. Decoupled timing: the emitter can be paused/resumed without
breaking the runner.

Design rationale (locked in for Phase 3)
----------------------------------------

Ticks are **ledger-resident**, not in-memory:

* **Wire-replay determinism** — the gap-escalation cluster decision
  depends on ``(tick_time, ledger_state_at_tick_time)``; both must
  be replayable. A tick in memory would not survive replay.
* **Audit completeness** — ticks are observable; "why did this
  escalation fire" is answerable from the ledger via the
  ``clock_tick`` entry plus the cluster-decision PEVR rows
  downstream.
* **Uniformity** — every fire path stays entry-driven; the runner
  contract stays unchanged.

Cost accepted: +1 entry kind (``clock_tick``), +per-tick ledger row,
+ClockTickEmitter daemon. If tick volume grows enough that ledger
storage becomes a concern, the projection layer can promote the tick
chain into a derived view + GC the raw entries (a "TICK_RETAIN_DAYS"
knob); the loop remains correct because the projection is just a
materialized view over the same source.

Recovery
--------

``sequence_number`` is computed by counting prior ``clock_tick``
entries for this ``(company_id, tick_interval_s)`` pair. If the
emitter daemon crashes and restarts, it reads the prior max
``sequence_number`` and continues. No external state, no checkpoint
file — the ledger itself is the checkpoint.

Quadrant: ``passive_deterministic``. Emitter output is fully a
function of ``(company_id, tick_interval_s, prior_count)``. There is
no LLM stochasticity, no external API, no user input — a tick is
deterministic given its inputs, and the inputs are themselves
deterministic (a configured cadence and the ledger row count). This
quadrant tag enables the ``passive`` write-path's reduced gate
budget (PII / warmup gates do not run on emitter writes).

Multi-cadence support
---------------------

``tick_interval_s`` is a per-emitter parameter, not a global default.
Phase 3+ can run multiple emitters with different cadences in parallel
(hourly for gap-escalation, daily for digest reactivities). Each
emitter writes its own ``clock_tick`` chain; the ``Periodic(every_seconds=N)``
predicate filters on matching cadence so distinct reactivities see only
their own ticks.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger("wormbase_reactivities.clock_tick_emitter")


class ClockTickEmitter:
    """Single-tenant clock-tick daemon. Parallel sibling to ReactivityRunner.

    Writes one ``clock_tick`` ledger entry every ``tick_interval_s``
    seconds. Cancel-safe (``asyncio.CancelledError`` propagates from
    :meth:`run_forever`). Tests can drive :meth:`tick_once` directly
    without sleeping.

    Construction is cheap (no I/O); the daemon does not connect to the
    ledger until the first tick is written. This keeps boot smoke tests
    from holding a live connection.
    """

    def __init__(
        self,
        ledger: Any,
        company_id: UUID,
        *,
        tick_interval_s: int,
    ) -> None:
        if tick_interval_s <= 0:
            raise ValueError(
                f"tick_interval_s must be positive; got {tick_interval_s}"
            )
        self._ledger = ledger
        self._company_id = company_id
        self._tick_interval_s = int(tick_interval_s)

    @property
    def tick_interval_s(self) -> int:
        return self._tick_interval_s

    @property
    def company_id(self) -> UUID:
        return self._company_id

    async def _next_sequence_number(self) -> int:
        """Return the next ``sequence_number`` for this emitter's slot.

        Counts the prior ``clock_tick`` execute entries on the ledger for
        this ``(company_id, tick_interval_s)`` pair. The count is the
        next 0-indexed sequence number — first tick is 0, second 1, etc.

        Restart-safe: a fresh daemon coming up after a crash sees N prior
        execute rows and continues with sequence_number=N. Multi-cadence
        safe: only ticks with the matching ``tick_interval_s`` count
        toward the slot.
        """
        rows = await self._ledger.fetch(self._company_id)
        prior = 0
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if payload.get("tool") != "emit_clock_tick":
                continue
            args = payload.get("args") or {}
            if not isinstance(args, dict):
                continue
            try:
                if int(args.get("tick_interval_s", -1)) == self._tick_interval_s:
                    prior += 1
            except (TypeError, ValueError):
                continue
        return prior

    async def tick_once(self) -> dict[str, Any]:
        """Emit exactly one tick. Returns the execute-row payload.

        Used by tests + the run_forever loop. Writes a canonical
        propose/execute/verify/resolve PEVR cycle so the
        ``ReactivityRunner`` sees the tick on the **execute** envelope
        (where ``Periodic.match`` matches) the same way it sees every
        other emit_*-shaped event.

        Each call computes its own sequence_number from the ledger so
        out-of-order or recovered ticks remain monotonic. The
        ``tick_interval_s`` is the emitter's configured cadence; per
        the design notes it is a per-emitter parameter, not global.
        """
        sequence_number = await self._next_sequence_number()
        payload: dict[str, Any] = {
            "tick_interval_s": self._tick_interval_s,
            "sequence_number": sequence_number,
        }

        # Canonical PEVR. The emitter's writes are passive_deterministic
        # — pure function of (company_id, tick_interval_s, prior_count).
        await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": "clock_tick",
                "ref_id": (
                    f"clock_tick:{self._company_id}:"
                    f"{self._tick_interval_s}:{sequence_number}"
                ),
                "reason": (
                    f"periodic tick every {self._tick_interval_s}s "
                    f"(seq={sequence_number})"
                ),
                "proposed_by": "reactivities.clock_tick_emitter",
            },
            execute_fn=lambda: {
                "tool": "emit_clock_tick",
                "args": dict(payload),
                "result_ref": (
                    f"clock_tick:{self._tick_interval_s}:{sequence_number}"
                ),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "clock_tick", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": (
                    f"clock_tick emitted: cadence={self._tick_interval_s}s "
                    f"sequence_number={sequence_number}"
                ),
            },
            quadrant="passive_deterministic",
        )
        return dict(payload)

    async def run_forever(self) -> None:
        """Periodic loop. Cancel-safe.

        Sleeps ``tick_interval_s`` between ticks. The very first tick
        fires AFTER the first sleep so a freshly-started emitter does
        not race with boot wiring. Tests that want immediate first
        ticks can call :meth:`tick_once` directly.

        Pattern mirrors :class:`ReactivityRunner.run_forever`: catch +
        log exceptions inside the loop body so a transient ledger
        failure does not crash the daemon; ``asyncio.CancelledError``
        always propagates to ensure clean shutdown.
        """
        logger.info(
            "clock_tick_emitter starting: company_id=%s tick_interval_s=%d",
            self._company_id, self._tick_interval_s,
        )
        while True:
            try:
                await asyncio.sleep(self._tick_interval_s)
            except asyncio.CancelledError:
                logger.info(
                    "clock_tick_emitter cancelled — clean shutdown "
                    "(company_id=%s tick_interval_s=%d)",
                    self._company_id, self._tick_interval_s,
                )
                raise
            try:
                payload = await self.tick_once()
                logger.debug(
                    "clock_tick_emitter tick: company_id=%s seq=%d",
                    self._company_id, payload.get("sequence_number"),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "clock_tick_emitter tick failed (company_id=%s): %s",
                    self._company_id, exc,
                )


__all__ = ["ClockTickEmitter"]
