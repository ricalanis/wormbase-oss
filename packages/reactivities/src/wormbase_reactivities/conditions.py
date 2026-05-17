"""Composable conditions for the Reactivity Protocol.

Conditions are the budget / novelty / governance gate between "predicate
matched" and "actually fire". Same composability shape as predicates —
``__and__`` / ``__or__`` / ``__invert__`` operators on the abstract base
let callers write:

    condition = (
        DailyBudget(per_owner=3, per_domain=10, per_tenant=50)
        & NotRecentlyFired("topic:owner", hours=4.0)
        & DomainEnabled()
    )

Conditions are STRICTLY READ-ONLY. They consult registry counters and
recent-fire history but never mutate them. The registry's ``dispatch``
loop increments budgets only after a successful fire, so conditions
that erroneously over-restrict don't cause budget leakage and conditions
that erroneously under-restrict don't cause silent counter drift.

Key tradeoffs:

* ``DailyBudget`` uses a rolling-day window keyed on UTC date. This is
  simpler than sliding-window-of-N-hours and matches the "no more than
  N DMs/day" UX intuition. Operators can override via env or per-tenant
  policy in a future wave.

* ``NotRecentlyFired`` is sliding-window — "if this exact (reactivity, key)
  fired in the last H hours, suppress". This is what enforces topic-novelty
  ("don't DM Bob about churn twice in 4 hours").

* ``DomainEnabled`` reaches into the registry's domain-policy state. The
  default registry treats every domain as enabled; future Reactivities that
  want admin-toggleable per-domain mute land here.

Why no "PerOwner / PerDomain / PerTenant" individual conditions? Because
DailyBudget(per_owner=N, per_domain=M, per_tenant=K) is the canonical
combined check. Splitting them invites callers to forget one axis. The
registry computes which axes to check based on the entry's owner_id /
domain_id / company_id; missing axes (no owner on this entry) are skipped
without erroring.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from wormbase_reactivities.protocol import (
    ReactivityCondition,
    ReactivityContext,
)


class _ConditionBase:
    """Mixin that wires the composition operators on ReactivityCondition.

    Same shape as ``predicates._PredicateBase``. Subclasses implement
    ``async def allows(self, entry, context) -> bool``; this base class
    layers the operator dunders so composition is uniform.
    """

    async def allows(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        raise NotImplementedError

    def __and__(self, other: ReactivityCondition) -> "And":
        return And(self, other)

    def __or__(self, other: ReactivityCondition) -> "Or":
        return Or(self, other)

    def __invert__(self) -> "Not":
        return Not(self)


def _entry_owner_id(entry: dict[str, Any]) -> str | None:
    """Pull the resource-owner id out of an entry's args, if present."""
    payload = entry.get("payload") or {}
    args = payload.get("args") or {}
    v = (
        args.get("owner_id")
        or args.get("owner_person")
        or args.get("owner_person_id")
    )
    return str(v) if v else None


def _entry_domain_id(entry: dict[str, Any]) -> str | None:
    """Pull the domain id out of an entry's args, if present."""
    payload = entry.get("payload") or {}
    args = payload.get("args") or {}
    v = args.get("domain_id") or args.get("domain")
    return str(v) if v else None


@dataclass
class DailyBudget(_ConditionBase):
    """Composed per-owner / per-domain / per-tenant rolling-day budget cap.

    Each axis is checked independently against the registry's
    ``reactivity_budget`` table. The reactivity_id (from context) keys
    every counter.

    Defaults follow the "first week of operation" envelope agreed in the
    Wave-5 plan: per-owner 3/day, per-domain 10/day, per-tenant 50/day.
    Operators can lower these per-tenant via /policies in a future wave.

    The "current day" boundary is UTC midnight — picked over local-time
    because tenancies span timezones; auditability beats convenience.
    """

    per_owner: int = 3
    per_domain: int = 10
    per_tenant: int = 50

    async def allows(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        registry = context.registry
        if registry is None:
            # No registry = no budget store = no caps. Useful for
            # synthetic tests that exercise predicate logic without
            # constructing a full registry.
            return True
        # The reactivity_id is always set on the context by the registry's
        # dispatch loop right before condition evaluation. If it's missing
        # we're in an integration error; deny so the bug surfaces fast.
        reactivity_id = context.extras.get("reactivity_id")
        if not reactivity_id:
            return False

        now = context.now() if callable(context.now) else context.now
        if not isinstance(now, datetime):
            return False
        day = now.date().isoformat()

        # Per-owner
        owner = _entry_owner_id(entry)
        if owner is not None and self.per_owner is not None:
            count = await registry.get_budget_count(
                reactivity_id=reactivity_id,
                axis="owner",
                key=owner,
                day=day,
            )
            if count >= self.per_owner:
                return False

        # Per-domain
        domain = _entry_domain_id(entry)
        if domain is not None and self.per_domain is not None:
            count = await registry.get_budget_count(
                reactivity_id=reactivity_id,
                axis="domain",
                key=domain,
                day=day,
            )
            if count >= self.per_domain:
                return False

        # Per-tenant
        if self.per_tenant is not None:
            count = await registry.get_budget_count(
                reactivity_id=reactivity_id,
                axis="tenant",
                key=str(context.company_id),
                day=day,
            )
            if count >= self.per_tenant:
                return False

        return True


@dataclass
class NotRecentlyFired(_ConditionBase):
    """Sliding-window novelty gate: deny if (reactivity, key) fired recently.

    ``novelty_key`` is a string template the caller picks. Common shapes:

      * ``"owner:topic"`` — for statement-to-owner; suppress repeat DMs
        about the same (owner, topic) within the window.
      * ``"kpi_gap"`` — for phenomenon-gap detectors; suppress repeated
        proposals of the same missing metric.
      * ``"autoresearch:metric"`` — suppress experiment proposals on the
        same metric within 24h.

    The condition resolves the actual key by reading
    ``context.extras["novelty_key"]`` if set; falling back to this
    instance's ``novelty_key`` literal. This indirection lets a single
    condition instance support reactivities that compute the key from
    the entry (vs. a reactivities that uses a fixed string).

    Window is in fractional hours so tests can use 0.001 to verify the
    boundary case without sleeping.
    """

    novelty_key: str = ""
    hours: float = 4.0

    async def allows(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        registry = context.registry
        if registry is None:
            return True
        reactivity_id = context.extras.get("reactivity_id")
        if not reactivity_id:
            return False

        # Either an explicit per-entry key (set by Reactivity.fire upstream
        # of the dispatch retry) or the literal instance key.
        key = context.extras.get("novelty_key", self.novelty_key)
        if not key:
            # No novelty axis configured → vacuously allow.
            return True

        now = context.now() if callable(context.now) else context.now
        if not isinstance(now, datetime):
            return False
        cutoff = now - timedelta(hours=self.hours)

        last_fired_at = await registry.get_last_fired_at(
            reactivity_id=reactivity_id,
            novelty_key=key,
        )
        if last_fired_at is None:
            return True
        return last_fired_at < cutoff


@dataclass
class Periodic(_ConditionBase):
    """Wall-clock period gate: allow at most once per UTC period bucket.

    Symmetric to ``NotRecentlyFired`` but anchored to wall-clock buckets
    rather than rolling-window-from-last-fire. Two reactivities composed
    with ``Periodic(period_seconds=86_400) & NotRecentlyFired(hours=24)``
    fire at most once per UTC day per (reactivity, novelty_key) — the
    Periodic side enforces the bucket boundary; the NotRecentlyFired
    side enforces the no-burst-replay invariant inside the same bucket.

    Used by F.4's ``KeepRatePublishReactivity`` to ratchet the keep-rate
    publisher to one fire per day per install regardless of how many
    ``experiment_resolved`` rows land in that window.

    The bucket is ``floor(now_unix / period_seconds)``. The condition
    consults ``registry.get_last_fired_at(reactivity_id, novelty_key)``
    and allows when:

      * No prior fire on record (first run), OR
      * The prior fire's bucket differs from the current bucket.

    ``novelty_key`` resolution mirrors ``NotRecentlyFired`` — explicit
    ``context.extras["novelty_key"]`` if set, else the instance literal.
    Same convention so reactivities can pair the two conditions with one
    novelty key.
    """

    period_seconds: int = 86_400
    novelty_key: str = ""

    async def allows(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        registry = context.registry
        if registry is None:
            return True
        reactivity_id = context.extras.get("reactivity_id")
        if not reactivity_id:
            return False

        key = context.extras.get("novelty_key", self.novelty_key)
        if not key:
            return True

        now = context.now() if callable(context.now) else context.now
        if not isinstance(now, datetime):
            return False

        last_fired_at = await registry.get_last_fired_at(
            reactivity_id=reactivity_id,
            novelty_key=key,
        )
        if last_fired_at is None:
            return True

        period = max(int(self.period_seconds), 1)
        now_bucket = int(now.timestamp()) // period
        last_bucket = int(last_fired_at.timestamp()) // period
        return now_bucket > last_bucket


@dataclass
class DomainEnabled(_ConditionBase):
    """Allow only when the entry's domain is enabled in registry policy.

    Reactivities that don't target a specific domain pass — there's
    nothing to check. When the domain IS present, the registry's
    ``is_domain_enabled`` is consulted. The default registry treats
    every domain as enabled; future Reactivities can wire admin-driven
    per-domain mute toggles by extending the registry's policy table.
    """

    async def allows(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        registry = context.registry
        if registry is None:
            return True
        domain = _entry_domain_id(entry)
        if domain is None:
            return True
        return await registry.is_domain_enabled(domain)


@dataclass
class And(_ConditionBase):
    """Logical AND over conditions; short-circuits at the first False.

    Empty list = True (vacuously). Same conventions as the predicate
    composition operators, kept aligned for cognitive load.
    """

    conditions: tuple[ReactivityCondition, ...] = field(default_factory=tuple)

    def __init__(self, *conditions: ReactivityCondition) -> None:
        self.conditions = conditions

    async def allows(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        for c in self.conditions:
            if not await c.allows(entry, context):
                return False
        return True


@dataclass
class Or(_ConditionBase):
    """Logical OR over conditions; short-circuits at the first True."""

    conditions: tuple[ReactivityCondition, ...] = field(default_factory=tuple)

    def __init__(self, *conditions: ReactivityCondition) -> None:
        self.conditions = conditions

    async def allows(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        for c in self.conditions:
            if await c.allows(entry, context):
                return True
        return False


@dataclass
class Not(_ConditionBase):
    """Logical negation."""

    condition: ReactivityCondition

    async def allows(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        return not await self.condition.allows(entry, context)


@dataclass
class AlwaysAllow(_ConditionBase):
    """Trivial pass-through condition.

    Useful for Reactivities that perform their own per-fire gating inside
    ``fire`` (e.g. ``IdentityDiscoveryReactivity`` deduplicates via the
    known-set, not via a Condition). Marker class so registry tests can
    distinguish "no condition" from "AlwaysAllow on purpose".
    """

    async def allows(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        return True


@dataclass
class LiveOnly(_ConditionBase):
    """Allow only push-delivered, fresh entries (the speak-path gate).

    Reads ``delivery_mode`` and ``platform_ts`` from
    ``entry.payload.args``; computes ``is_live`` as
    ``(delivery_mode == "push") AND (entry.ts - platform_ts < window)``.
    Permissive when the fields are missing — back-compat for
    pre-provenance ledger entries (defaults to live-and-fresh).

    Used by F1/F2/F4 chat-presence reactivities to suppress fires from
    history-replay (WhatsApp/Baileys reconnect) and stale-fetch
    (Slack reconnect) flows. F3 InterjectionBudgetReactivity is
    observation-only and intentionally NOT gated.

    Freshness window: 60s default; override via
    ``WORMBASE_FRESHNESS_WINDOW_S`` env var (parsed each call so tests
    can patch with ``monkeypatch.setenv``).
    """

    async def allows(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        args = (entry.get("payload") or {}).get("args") or {}
        # delivery_mode: any non-"push" value (history_sync, future modes)
        # blocks. Missing field defaults to "push" for back-compat.
        if args.get("delivery_mode", "push") != "push":
            return False

        platform_ts_raw = args.get("platform_ts")
        if not platform_ts_raw:
            # No platform timestamp → can't compute staleness; permissive.
            return True

        # Normalize platform_ts: accepts datetime or ISO-8601 string
        # (Z-suffix or +00:00). Pre-provenance entries written before
        # the LiveOnly gate landed never had this field, so we treat
        # parse failure as permissive too.
        if isinstance(platform_ts_raw, datetime):
            pts = platform_ts_raw
        else:
            try:
                pts = datetime.fromisoformat(
                    str(platform_ts_raw).replace("Z", "+00:00"),
                )
            except (ValueError, TypeError):
                return True
        if pts.tzinfo is None:
            pts = pts.replace(tzinfo=timezone.utc)

        # Normalize ingest ts (entry.ts) the same way; fall back to
        # context.now() if absent.
        ingest_ts: Any = entry.get("ts")
        if ingest_ts is None:
            ingest_ts = context.now() if callable(context.now) else context.now
            if not isinstance(ingest_ts, datetime):
                ingest_ts = datetime.now(timezone.utc)
        if isinstance(ingest_ts, str):
            try:
                ingest_ts = datetime.fromisoformat(
                    ingest_ts.replace("Z", "+00:00"),
                )
            except (ValueError, TypeError):
                return True
        if not isinstance(ingest_ts, datetime):
            return True
        if ingest_ts.tzinfo is None:
            ingest_ts = ingest_ts.replace(tzinfo=timezone.utc)

        threshold_raw = os.environ.get("WORMBASE_FRESHNESS_WINDOW_S", "60")
        try:
            threshold = float(threshold_raw)
        except ValueError:
            threshold = 60.0
        return (ingest_ts - pts).total_seconds() < threshold


__all__ = [
    "AlwaysAllow",
    "And",
    "DailyBudget",
    "DomainEnabled",
    "LiveOnly",
    "NotRecentlyFired",
    "Not",
    "Or",
    "Periodic",
]
