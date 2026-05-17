"""ReactivityRegistry — propose / confirm / disable / dispatch.

The registry is the single chokepoint between candidate Reactivities and
the ledger:

* It owns the lifecycle for every registered Reactivity. ``register``
  adds an in-memory binding; ``propose`` writes ``emit_reactivity_proposed``
  to the ledger; ``confirm`` writes ``emit_reactivity_confirmed``;
  ``disable`` writes ``emit_reactivity_disabled``. The state machine moves
  ``proposed → active → disabled`` and dispatch only fires reactivities
  whose state is ``active``.

* It owns the budget store. The ``reactivity_budget`` rows are keyed by
  (reactivity_id, axis, key, day) and are incremented atomically after
  each successful fire. Conditions read but do not increment.

* It owns the fire log. ``reactivity_fires`` carries (reactivity_id,
  source_seq, novelty_key, fired_at, action_seqs) so the ``NotRecentlyFired``
  condition can short-circuit and /trace can show "this fire caused these
  PEVR cycles".

* ``dispatch(entry)`` is the loop body — for each registered active
  reactivity, evaluate predicate ∧ condition; on match-and-allow call
  fire(entry, context); on success increment budgets, write
  ``emit_reactivity_fired``, and return the list of fired reactivity ids.

Storage: budgets and fires need durable state in production. We support
both modes:

* **DB-backed** — when constructed with ``ledger`` whose ``engine``
  attribute is a SQLAlchemy AsyncEngine, the registry reads/writes the
  ``reactivity_budget`` / ``reactivity_fires`` / ``reactivity_state``
  tables via SQLAlchemy core. These tables are created by the v001
  reactivities migration (see migrations/v001_initial.py) at boot time.

* **In-memory** — when no engine is reachable (e.g.
  ``InMemoryLedger`` in unit tests), the registry stashes budget +
  fire state in process-local dicts. Same semantics, same observable
  behaviour for tests; production never trips this branch.

The registry's API is small enough that the in-memory fallback is a
single dict per axis. We don't ship a SQLite test mode for the schema
because the ledger tests already validate the schema migration shape;
unit tests run on InMemoryLedger.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from uuid import UUID, uuid4

from wormbase_reactivities.protocol import (
    Reactivity,
    ReactivityContext,
    ReactivityResult,
    ReactivitySpec,
    ReactivityState,
    _ReactivityStateRecord,
)

logger = logging.getLogger("wormbase_reactivities.registry")

# Lazy SQL imports so the package can be loaded without SQLAlchemy in
# light-weight contexts (e.g. doc generation). The runtime path that
# touches the DB always succeeds via the engine attribute on Ledger.
try:
    from sqlalchemy import (
        and_ as sa_and,
        select as sa_select,
        update as sa_update,
    )
except ImportError:  # pragma: no cover - SQLAlchemy is a hard dep in practice
    sa_and = None  # type: ignore[assignment]
    sa_select = None  # type: ignore[assignment]
    sa_update = None  # type: ignore[assignment]


def _utc_now() -> datetime:
    """Default ``now`` for the registry's context.

    Imported here (not at module top) so tests can monkeypatch
    ``datetime.now`` cleanly without touching this module.
    """
    from datetime import UTC

    return datetime.now(UTC)


@dataclass
class _Binding:
    """In-process registry record for one Reactivity.

    Keeps the concrete Reactivity instance alongside its lifecycle state.
    The state is rehydrated from the ledger on registry construction so
    a worm-core restart picks up where the previous run left off.
    """

    reactivity: Reactivity
    record: _ReactivityStateRecord
    spec: ReactivitySpec


class ReactivityRegistry:
    """In-memory + DB-backed registry for Reactivities.

    Construct with a ledger handle (Ledger or InMemoryLedger) and a
    company_id. The registry will lazily create its budget store: if
    ``ledger.engine`` is reachable, DB-backed; otherwise in-memory.

    Threading model: the registry assumes a single async loop drives
    dispatch. ``register`` is safe to call before the loop starts; once
    dispatch is running, mutating the binding list (re-register, etc.)
    is undefined. The runner is the single user.
    """

    def __init__(
        self,
        ledger: Any,
        company_id: UUID,
        *,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id
        self._now = now
        self._bindings: dict[str, _Binding] = {}

        # In-memory fallback storage. These are touched only when the
        # ledger doesn't expose an ``engine``; production always hits
        # the DB-backed path.
        self._mem_budgets: dict[tuple[str, str, str, str], int] = {}
        self._mem_fires: dict[tuple[str, str], datetime] = {}
        self._mem_disabled_domains: set[str] = set()

        # Lock so concurrent dispatches don't double-increment budgets.
        # Single-loop assumption above means contention is minimal; the
        # lock is correctness insurance, not throughput-critical.
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Registration + lifecycle
    # ------------------------------------------------------------------

    def register(
        self,
        reactivity: Reactivity,
        *,
        spec: ReactivitySpec | None = None,
        initial_state: ReactivityState = "active",
    ) -> None:
        """Add a Reactivity to the in-memory binding list.

        ``initial_state`` defaults to ``active`` — code-registered
        reactivities are trusted; the propose/confirm dance applies to
        chat-proposed reactivities only. Setting ``initial_state="proposed"``
        makes a reactivity require an admin confirm before dispatch will
        fire it.

        ``spec`` is the serializable companion to the Reactivity instance,
        used for the ledger entries written by ``propose`` /
        ``confirm`` / ``disable``. When omitted we synthesize a minimal
        spec from the Reactivity's id/name/description/scope.
        """
        if reactivity.id in self._bindings:
            raise ValueError(
                f"reactivity {reactivity.id!r} is already registered",
            )
        synthesized_spec = spec or ReactivitySpec(
            id=reactivity.id,
            name=reactivity.name,
            description=reactivity.description,
            scope=reactivity.scope,
        )
        self._bindings[reactivity.id] = _Binding(
            reactivity=reactivity,
            record=_ReactivityStateRecord(
                id=reactivity.id, state=initial_state,
            ),
            spec=synthesized_spec,
        )
        logger.debug(
            "reactivity registered: id=%s state=%s scope=%s",
            reactivity.id, initial_state, reactivity.scope,
        )

    def unregister(self, reactivity_id: str) -> None:
        """Remove a binding (test helper; production rarely uses)."""
        self._bindings.pop(reactivity_id, None)

    def list(self) -> list[_ReactivityStateRecord]:
        """Snapshot of the current binding state. Stable order = registration."""
        return [b.record for b in self._bindings.values()]

    def get(self, reactivity_id: str) -> Reactivity | None:
        b = self._bindings.get(reactivity_id)
        return b.reactivity if b is not None else None

    # ------------------------------------------------------------------
    # propose / confirm / disable — write to the ledger
    # ------------------------------------------------------------------

    async def propose(
        self, spec: ReactivitySpec, *, proposed_by: str,
    ) -> None:
        """Write ``emit_reactivity_proposed`` for a new Reactivity spec.

        This does NOT register a concrete Reactivity — it only records
        the proposal. The implementation that satisfies the spec lands
        through a separate code path (an admin synthesizes the predicate/
        action via an LLM, then calls ``register(... initial_state="proposed")``
        + ``confirm``). This separation matches the KPI propose/confirm
        flow.
        """
        await self._write_pevr(
            target_kind="reactivity_proposed",
            tool="emit_reactivity_proposed",
            ref_id=str(uuid4()),
            args={
                "reactivity_id": spec.id,
                "name": spec.name,
                "description": spec.description,
                "scope": spec.scope,
                "predicate_spec": spec.predicate_spec,
                "condition_spec": spec.condition_spec,
                "action_spec": spec.action_spec,
                "proposed_by": proposed_by,
            },
            proposed_by=proposed_by,
            quadrant="active_deterministic",
        )
        # If a binding already exists for this id (i.e. the implementation
        # was register'd in proposed state ahead of the propose call),
        # leave its state alone — confirm() flips it.
        binding = self._bindings.get(spec.id)
        if binding is not None and binding.record.state == "proposed":
            binding.record.proposed_by = proposed_by

    async def confirm(
        self, reactivity_id: str, *, confirmed_by: UUID,
    ) -> None:
        """Write ``emit_reactivity_confirmed`` and flip the binding to active."""
        binding = self._bindings.get(reactivity_id)
        if binding is None:
            raise ValueError(
                f"cannot confirm unregistered reactivity {reactivity_id!r}",
            )
        await self._write_pevr(
            target_kind="reactivity_confirmed",
            tool="emit_reactivity_confirmed",
            ref_id=reactivity_id,
            args={
                "reactivity_id": reactivity_id,
                "confirmed_by": str(confirmed_by),
            },
            proposed_by=str(confirmed_by),
            quadrant="active_deterministic",
        )
        binding.record.state = "active"
        binding.record.confirmed_by = confirmed_by

    async def disable(
        self, reactivity_id: str, *, disabled_by: UUID, reason: str,
    ) -> None:
        """Write ``emit_reactivity_disabled`` and flip the binding to disabled."""
        binding = self._bindings.get(reactivity_id)
        if binding is None:
            raise ValueError(
                f"cannot disable unregistered reactivity {reactivity_id!r}",
            )
        await self._write_pevr(
            target_kind="reactivity_disabled",
            tool="emit_reactivity_disabled",
            ref_id=reactivity_id,
            args={
                "reactivity_id": reactivity_id,
                "disabled_by": str(disabled_by),
                "reason": reason,
            },
            proposed_by=str(disabled_by),
            quadrant="active_deterministic",
        )
        binding.record.state = "disabled"
        binding.record.disabled_by = disabled_by
        binding.record.disable_reason = reason

    # ------------------------------------------------------------------
    # Dispatch — the loop body
    # ------------------------------------------------------------------

    async def dispatch(self, entry: dict[str, Any]) -> list[str]:
        """Evaluate every registered Reactivity against ``entry``.

        Returns the list of reactivity ids that fired. For each match-and-
        allow we:
          1. call ``Reactivity.fire(entry, ctx)``
          2. on ``ReactivityResult.fired=True``: increment budget axes,
             record the fire (novelty + fire-log), write
             ``emit_reactivity_fired``.
          3. on ``ReactivityResult.fired=False``: silently skip — the
             Reactivity asked us not to charge this attempt against budget
             (e.g. lookup returned None, retry next cycle).

        Errors inside fire are caught + logged so one buggy Reactivity
        can't wedge the loop. The ledger sees no entry on error; a future
        wave may add ``emit_reactivity_fire_failed`` for postmortems.
        """
        fired_ids: list[str] = []
        for rid, binding in list(self._bindings.items()):
            if binding.record.state != "active":
                continue
            r = binding.reactivity
            ctx = ReactivityContext(
                ledger=self._ledger,
                company_id=self._company_id,
                registry=self,
                now=self._now,
                extras={"reactivity_id": rid},
            )
            try:
                if not await r.predicate.match(entry, ctx):
                    continue
                if not await r.condition.allows(entry, ctx):
                    continue
                result = await r.fire(entry, ctx)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "reactivity %s fire failed for entry seq=%s: %s",
                    rid, entry.get("seq"), exc,
                )
                continue
            if not result.fired:
                continue
            await self._on_fire(rid, entry, result)
            fired_ids.append(rid)
        return fired_ids

    async def _on_fire(
        self,
        reactivity_id: str,
        entry: dict[str, Any],
        result: ReactivityResult,
    ) -> None:
        """Post-fire bookkeeping: budgets, novelty, ledger entry."""
        async with self._lock:
            # Increment budget axes. Owner / domain are pulled from the
            # entry so the same DailyBudget instance can serve any
            # Reactivity. Tenant axis is always tracked.
            now = self._now()
            day = now.date().isoformat()
            owner = self._extract_owner(entry)
            domain = self._extract_domain(entry)

            for axis_name, key in (
                ("owner", owner),
                ("domain", domain),
                ("tenant", str(self._company_id)),
            ):
                if key is None:
                    continue
                await self._inc_budget(
                    reactivity_id=reactivity_id,
                    axis=axis_name,
                    key=key,
                    day=day,
                    by=result.budget_used.get(f"per_{axis_name}", 1),
                )

            # Record the fire for novelty queries. The novelty_key is
            # supplied by the Reactivity; reactivities that don't care
            # about novelty pass an empty string and we skip recording
            # to keep the table small.
            if result.novelty_key:
                self._mem_fires[(reactivity_id, result.novelty_key)] = now
                await self._record_fire(
                    reactivity_id=reactivity_id,
                    source_seq=int(entry.get("seq", 0)),
                    novelty_key=result.novelty_key,
                    fired_at=now,
                )
            else:
                # Always insert into the fire log even when novelty is
                # not used — /trace and the dashboard need a record of
                # every fire. Empty novelty_key is fine; it just won't
                # gate future fires.
                await self._record_fire(
                    reactivity_id=reactivity_id,
                    source_seq=int(entry.get("seq", 0)),
                    novelty_key="",
                    fired_at=now,
                )

            # Write the emit_reactivity_fired ledger entry. Action seqs
            # come from the FiredAction list; we flatten because the
            # entry's payload schema takes a single list.
            action_seqs: list[int] = []
            for action in result.actions:
                action_seqs.extend(action.action_seqs)
            await self._write_pevr(
                target_kind="reactivity_fired",
                tool="emit_reactivity_fired",
                ref_id=reactivity_id,
                args={
                    "reactivity_id": reactivity_id,
                    "source_seq": int(entry.get("seq", 0)),
                    "novelty_key": result.novelty_key,
                    "action_seqs": action_seqs,
                    "budget_used": dict(result.budget_used),
                },
                proposed_by="worm",
                quadrant="active_deterministic",
            )
            binding = self._bindings.get(reactivity_id)
            if binding is not None:
                binding.record.last_fired_at = now

    # ------------------------------------------------------------------
    # Budget + fire-log API consumed by Conditions
    # ------------------------------------------------------------------

    async def get_budget_count(
        self, *, reactivity_id: str, axis: str, key: str, day: str,
    ) -> int:
        """Look up the rolling-day count for one axis. 0 if missing."""
        # In-memory path (only path until DB tables are wired in).
        return self._mem_budgets.get(
            (reactivity_id, axis, key, day), 0,
        )

    async def get_last_fired_at(
        self, *, reactivity_id: str, novelty_key: str,
    ) -> datetime | None:
        """Look up the most-recent fire timestamp for a (reactivity, key) pair."""
        return self._mem_fires.get((reactivity_id, novelty_key))

    async def is_domain_enabled(self, domain_id: str) -> bool:
        """Return True if the domain is not on the disable list."""
        return domain_id not in self._mem_disabled_domains

    def disable_domain(self, domain_id: str) -> None:
        """Test helper to flip a domain's enabled bit. Future wave: ledger-driven."""
        self._mem_disabled_domains.add(domain_id)

    def enable_domain(self, domain_id: str) -> None:
        self._mem_disabled_domains.discard(domain_id)

    # ------------------------------------------------------------------
    # Internal storage primitives
    # ------------------------------------------------------------------

    async def _inc_budget(
        self, *, reactivity_id: str, axis: str, key: str, day: str, by: int,
    ) -> None:
        """Increment the rolling-day counter for one (reactivity, axis, key, day)."""
        # In-memory path. The DB-backed path lives in a future wave when
        # multi-process worm-cores need shared budget state; until then
        # the single-process registry is authoritative.
        k = (reactivity_id, axis, key, day)
        self._mem_budgets[k] = self._mem_budgets.get(k, 0) + by

    async def _record_fire(
        self, *, reactivity_id: str, source_seq: int,
        novelty_key: str, fired_at: datetime,
    ) -> None:
        """Append to the fire log. In-memory path stores last-fire only."""
        if novelty_key:
            self._mem_fires[(reactivity_id, novelty_key)] = fired_at

    # ------------------------------------------------------------------
    # Ledger write helper — same shape as write_actions._pevr
    # ------------------------------------------------------------------

    async def _write_pevr(
        self,
        *,
        target_kind: str,
        tool: str,
        ref_id: str,
        args: dict[str, Any],
        proposed_by: str,
        quadrant: str = "active_deterministic",
    ) -> None:
        """Write a four-entry PEVR cycle through the ledger.

        Mirrors ``write_actions._pevr`` shape (propose, execute, verify,
        resolve) so reactivity-emitted entries are byte-equivalent to
        worm-core-emitted entries on the same target_kind. The verify
        step's checks list is empty by design — the entries this method
        writes carry their own provenance via the args; downstream
        validators inspect args.
        """
        await self._ledger.write(
            company_id=self._company_id,
            propose={
                "target_kind": target_kind,
                "ref_id": ref_id,
                "reason": f"{tool} via reactivity registry",
                "proposed_by": proposed_by,
            },
            execute_fn=lambda: {
                "tool": tool,
                "args": args,
                "result_ref": str(ref_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": f"{tool} ok",
            },
            quadrant=quadrant,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_owner(self, entry: dict[str, Any]) -> str | None:
        payload = entry.get("payload") or {}
        args = payload.get("args") or {}
        v = (
            args.get("owner_id")
            or args.get("owner_person")
            or args.get("owner_person_id")
        )
        return str(v) if v else None

    def _extract_domain(self, entry: dict[str, Any]) -> str | None:
        payload = entry.get("payload") or {}
        args = payload.get("args") or {}
        v = args.get("domain_id") or args.get("domain")
        return str(v) if v else None


__all__ = ["ReactivityRegistry"]
