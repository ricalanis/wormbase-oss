"""Projection-builder runner.

Long-lived async loop that polls the ledger for new entries and
materialises them into the SQL ``projection_*`` tables via the canonical
``build_projections`` fold + ``persist_projections`` writer.

Architectural fit: the Triad (a16z institutional + Karpathy memory +
autoresearch) calls for compounding state at near-zero maintenance
cost. The ledger is the source of truth (TRACE); the projection_*
tables are pre-materialised aggregations that let the dashboard read
without re-folding the entire ledger on every request.

Without this runner the projection_* tables stay empty and the
dashboard compensates with a TS-side fold-at-request — functional, but
slow and not architecture-correct.

Algorithm (v1, simplest viable):
    1. Fetch all ledger rows for the tenant.
    2. Detect tenant reset (max_seq < cursor) and rewind to 0.
    3. If new rows arrived since last cursor, run build_projections()
       on the full row set, then persist_projections() on the result.
    4. Sleep poll_interval_s and repeat.

Incremental fold (apply only new rows, no full rebuild) is a v2
optimisation. Full rebuild is fast at single-tenant scale and keeps
the v1 architecture simple — the persist path is tenant-scoped
delete + insert, which is already idempotent.

CLI wiring: registered in ``cli._run_async`` as a reactivity task
alongside chat_received_reactivity_poller, identity_discovery, and
the W5a ReactivityRunner (which now drives the process and research
Reactivities formerly run as polling loops).
"""

from __future__ import annotations

import asyncio
import logging
import os
from uuid import UUID

from wormbase_ledger import Ledger
from wormbase_ledger.db import session_scope
from wormbase_ledger.projections import build_projections, persist_projections
from wormbase_ledger.projections.migrate import current_version
from wormbase_ledger.projections.migrations import MIGRATIONS

logger = logging.getLogger("wormbase_core.projection_runner")

# Minimum projection-schema version this runner is compiled against.
# Computed from the canonical migration list — every migration in the
# tree at build time must be applied before the runner is allowed to
# write. The CLI's boot-time ``migrate(ledger)`` call is the producer;
# this constant is the consumer-side precondition that documents the
# contract and prevents silent drift if migrate() is ever skipped.
_REQUIRED_SCHEMA_VERSION = max((m.version for m in MIGRATIONS), default=0)


def _default_interval_s() -> float:
    """Pick the poll interval from env, with dev/prod-flavoured defaults.

    Convention: dev (5s), prod (30s), explicit override via
    ``WORM_CORE_PROJECTION_INTERVAL_S``.
    """
    raw = os.environ.get("WORM_CORE_PROJECTION_INTERVAL_S")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    is_dev = os.environ.get("WORMBASE_DEV", "").strip().lower() in ("1", "true")
    return 5.0 if is_dev else 30.0


class ProjectionRunner:
    """Polls the ledger and rebuilds the SQL projection_* tables.

    Single-tenant: one runner per (Ledger, company_id). The runner's
    own cursor (``_last_seq``) lets it skip work when no new ledger
    rows have landed. Tenant-reset detection (max_seq < _last_seq)
    rewinds the cursor and rebuilds from scratch — the persist path
    is tenant-scoped delete + insert, so this is byte-stable.
    """

    def __init__(
        self,
        ledger: Ledger,
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
        self._last_seq: int = 0
        # Hash of the row at ``_last_seq``. Lets the runner detect a
        # tenant wipe + re-seed that lands on the same seq counter
        # (4-entry cycle in / 4-entry cycle out → identical max_seq but
        # a different hash chain).
        self._last_hash: bytes | None = None

    @property
    def last_seq(self) -> int:
        return self._last_seq

    async def run_once(self) -> int:
        """One pass: fold ledger → persist projections.

        Returns the number of new rows folded this pass (0 means
        nothing to do). Tenant-reset detection: rewinds the cursor
        and rebuilds when the ledger went empty, when ``max_seq <
        _last_seq``, or when the row at ``_last_seq`` has a different
        hash than the runner's stored ``_last_hash`` (wipe + re-seed
        landing on the same counter).
        """
        rows = await self._ledger.fetch(self._company_id)
        if not rows:
            # Tenant has no ledger entries (yet) OR the ledger was just
            # wiped. Either way, rewind the cursor and clear projections.
            if self._last_seq != 0:
                logger.info(
                    "projection_runner: tenant reset detected (rows empty), "
                    "rewinding cursor company_id=%s prev_seq=%d",
                    self._company_id, self._last_seq,
                )
                self._last_seq = 0
                self._last_hash = None
                # Persist an empty Projections to clear stale rows.
                async with session_scope(self._ledger.engine) as session:
                    proj = await build_projections(session, self._company_id)
                async with self._ledger.engine.begin() as conn:
                    await persist_projections(conn, self._company_id, proj)
            return 0

        max_seq = max(r["seq"] for r in rows)
        reset_detected = False
        if max_seq < self._last_seq:
            # Tenant reset: a wipe + re-seed produced a smaller max_seq
            # than we'd previously committed to.
            logger.info(
                "projection_runner: tenant reset detected (max_seq < cursor), "
                "rewinding cursor company_id=%s prev_seq=%d new_max=%d",
                self._company_id, self._last_seq, max_seq,
            )
            reset_detected = True
        elif self._last_seq > 0 and self._last_hash is not None:
            # Same-seq-counter reset: the row at our cursor exists but
            # has a different hash. This indicates a wipe + re-seed that
            # landed on the same seq counter we'd previously processed.
            cursor_row = next(
                (r for r in rows if r["seq"] == self._last_seq), None,
            )
            if cursor_row is not None and cursor_row["hash"] != self._last_hash:
                logger.info(
                    "projection_runner: tenant reset detected "
                    "(hash mismatch at seq=%d), rewinding cursor company_id=%s",
                    self._last_seq, self._company_id,
                )
                reset_detected = True

        if reset_detected:
            self._last_seq = 0
            self._last_hash = None

        new_count = sum(1 for r in rows if r["seq"] > self._last_seq)
        if new_count == 0 and max_seq == self._last_seq and not reset_detected:
            return 0

        async with session_scope(self._ledger.engine) as session:
            proj = await build_projections(session, self._company_id)

        async with self._ledger.engine.begin() as conn:
            await persist_projections(conn, self._company_id, proj)

        self._last_seq = max_seq
        # Stash the hash of the new tail so the next pass can detect a
        # wipe-and-re-seed that lands on the same seq counter.
        tail = next((r for r in rows if r["seq"] == max_seq), None)
        self._last_hash = tail["hash"] if tail is not None else None
        if new_count:
            logger.debug(
                "projection_runner persisted: company_id=%s new_rows=%d max_seq=%d",
                self._company_id, new_count, max_seq,
            )
        return max(new_count, 1 if reset_detected else 0)

    async def run_forever(self) -> None:
        """Run ``run_once`` on a periodic timer. Cancel-safe.

        Preconditions:
            - The ledger's projection-schema version is at or above
              ``_REQUIRED_SCHEMA_VERSION``. The CLI's startup path
              calls ``migrate(ledger)`` before constructing the
              runner; this check documents the contract and converts
              an "operator forgot to wire the migrator" bug into a
              loud, recoverable startup failure rather than a silent
              column-missing crash on first poll.
        """
        # Schema-version precondition. We don't run migrations here —
        # the CLI is the canonical migrator — but we refuse to start
        # against a stale schema so the failure mode is "loud at
        # boot" rather than "subtle during polling".
        try:
            schema_v = await current_version(self._ledger)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "projection_runner: could not read schema version: %s "
                "(continuing — first poll will surface any drift)",
                exc,
            )
            schema_v = _REQUIRED_SCHEMA_VERSION
        if schema_v < _REQUIRED_SCHEMA_VERSION:
            raise RuntimeError(
                f"projection_runner: schema version {schema_v} is older "
                f"than required v{_REQUIRED_SCHEMA_VERSION}. The CLI must "
                "call migrate(ledger) before starting the runner. "
                "If this fired on a fresh install, check that the "
                "boot-time migration step ran cleanly."
            )

        logger.info(
            "projection_runner starting: company_id=%s interval=%.1fs schema_v=%d",
            self._company_id, self._poll_interval_s, schema_v,
        )
        # Initial run on startup so projection_* tables are populated as
        # soon as the worm-core process boots, even on a quiet tenant.
        try:
            await self.run_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("projection_runner initial run failed: %s", exc)

        while True:
            try:
                await asyncio.sleep(self._poll_interval_s)
            except asyncio.CancelledError:
                raise
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("projection_runner cycle failed: %s", exc)
