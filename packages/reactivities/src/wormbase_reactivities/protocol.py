"""Reactivity Protocol — the foundational abstraction for reactivities-as-data.

WormBase has historically grown ~5 hand-coded reactivity loops in worm-core
(``identity_discovery``, ``process_extractor``, ``chat_received_reactivity_poller``,
the autoresearch loops, etc.). They share a common shape:

* Watch the ledger for entries matching a *predicate* (semantic match).
* Decide whether to fire based on a *condition* (budget, novelty, gates).
* On match-and-allow, call a *fire* action that emits a PEVR cycle.

But they were written one at a time with no shared abstraction — you can't
propose a new reactivity from chat, can't disable one without a code deploy,
can't see at /trace which reactivity fired for a given entry.

This module is the abstraction. A `Reactivity` is now first-class state
with a ``proposed → confirmed → active → disabled`` lifecycle, the same
governance pattern used by KPIs, Sources, and Persons. Each Reactivity
carries:

  * a stable ``id`` (e.g. ``"identity_discovery"``)
  * a ``scope`` ∈ {company, team, domain, person}
  * a ``state`` ∈ {proposed, active, disabled}
  * a composable ``predicate`` (matches entries)
  * a composable ``condition`` (budget + novelty gating)
  * an ``async fire(entry, context)`` action that emits PEVR cycles

The composability of predicates/conditions is the load-bearing design
choice: the existing 5 reactivity loops can be expressed as combinations
of a handful of primitive predicates (EntryKind, HasTopic, HasOwner,
SpeakerNotOwner, ...) and conditions (DailyBudget, NotRecentlyFired,
DomainEnabled, ...). Future Reactivities — statement-to-owner,
phenomenon-gap detectors, autoresearch-as-reactivity — slot in by
combining the same primitives, no protocol changes needed.

Conceptual sketches for future Reactivities (proves the Protocol survives
them — see W5.A2/A3 plan for full implementations):

    StatementToOwnerReactivity:
        predicate = EntryKind("chat_received") & HasTopic() & SpeakerNotOwner()
        condition = (
            DailyBudget(per_owner=3, per_domain=10, per_tenant=50)
            & NotRecentlyFired("topic:owner", hours=4.0)
            & DomainEnabled()
        )
        fire     = DM the owner with kpi/sources/decisions/processes for topic

    KpiReferenceWithoutKpiReactivity:
        predicate = EntryKind("chat_received") & MentionsMetric() & ~MetricInKpiTree()
        condition = NotRecentlyFired("kpi_gap", hours=1.0) & DomainEnabled()
        fire     = propose a KPI node + emit_phenomenon_gap_detected

    AutoresearchAsReactivity (Person-scope):
        predicate = EntryKind("metric_observed") & MetricBelowThreshold()
        condition = DailyBudget(per_owner=5) & NotRecentlyFired("autoresearch:metric", hours=24)
        fire     = propose an experiment_proposed PEVR cycle

The Protocol is intentionally minimal. Predicate and Condition are async
because future implementations will hit the inference router for semantic
matching; making them sync now would be a footgun. ReactivityContext is the
sole channel for side-effects so unit tests can swap a real ledger for an
InMemoryLedger and assert the same behaviour.
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

# Scope of a Reactivity. Higher scope = higher priority on conflict
# arbitration (Company > Team > Domain > Person), matching W5.A4's
# autoresearch arbitration rule.
ReactivityScope = Literal["company", "team", "domain", "person"]

# Lifecycle state. Reactivities are proposed (audit-only) and only fire
# once an admin confirms; admins can disable to stop future fires while
# preserving history. Same shape as KPI/Person/Source proposals.
ReactivityState = Literal["proposed", "active", "disabled"]


@dataclass
class ReactivityContext:
    """Mutable side-effect surface threaded through predicate/condition/fire.

    Carries the ledger handle the Reactivity uses to write its PEVR cycles,
    the company_id of the tenant being processed, the registry (so a
    Reactivity can query budget state and prior fires), and a ``now``
    callable so tests can freeze time.

    ``extras`` is the escape hatch: domain-specific helpers (member
    lookups, owner resolvers, topic extractors) can be injected without
    changing the dataclass. Concrete Reactivities document the keys they
    expect.
    """

    ledger: Any  # wormbase_ledger.Ledger | InMemoryLedger
    company_id: UUID
    registry: Any  # ReactivityRegistry — typed as Any to break import cycle
    now: Any  # callable returning tz-aware datetime
    extras: dict[str, Any] = field(default_factory=dict)
    # v2.A D5 — wire-replay determinism. When True, Reactivities that
    # perform external side-effects (HTTP POST, queue push, etc.) must
    # no-op the side-effect while still writing the audit ledger entry
    # so replayed runs reproduce byte-identical ledger state without
    # double-notifying external systems. Additive field — default False
    # preserves byte-identical behaviour for all existing callers.
    replay_mode: bool = False


@dataclass
class FiredAction:
    """Record of one PEVR cycle a Reactivity emitted on fire.

    ``action_seqs`` are the seqs of the four entries (propose, execute,
    verify, resolve). The registry's ``emit_reactivity_fired`` ledger entry
    records these so /trace can show "reactivity X fired here, here are
    the entries it caused".
    """

    action_kind: str  # e.g. "person_proposed"
    action_seqs: list[int] = field(default_factory=list)


@dataclass
class ReactivityResult:
    """What ``Reactivity.fire`` returned to the registry.

    ``fired`` indicates whether the reactivity actually performed an action
    (False means it was a no-op for an idiomatic reason — e.g. lookup
    returned None and the reactivity wants to retry next cycle). The registry
    only writes ``emit_reactivity_fired`` when ``fired=True``.

    ``actions`` is the list of PEVR cycles emitted. Most reactivities emit
    one; some emit several (e.g. propose + identity_link in one fire).

    ``novelty_key`` is what the registry will record so subsequent cycles
    can apply NotRecentlyFired logic. Reactivities that don't care about
    novelty pass an empty string.

    ``budget_used`` is a small dict like {"per_owner": 1} that the registry
    increments against the rolling-day counters. Each Reactivity's condition
    decides which buckets to charge.
    """

    fired: bool
    actions: list[FiredAction] = field(default_factory=list)
    novelty_key: str = ""
    budget_used: dict[str, int] = field(default_factory=dict)


# @runtime_checkable on the Reactivity Protocol family is part of the durable
# W5a contract (audit landed 2026-05-04, deferred-backlog wave). Conformance
# tests across packages depend on isinstance(x, Reactivity)-style checks; do
# not remove the decorator without coordinating across all consumers.
@runtime_checkable
class ReactivityPredicate(Protocol):
    """Async, composable matcher over a ledger entry.

    Returns True when the entry is eligible to fire this reactivity. Should
    NOT consult budgets — that's the Condition's job. Should be cheap;
    expensive lookups (semantic match, owner resolution) belong inside fire().

    Implementations get composability for free via ``__and__`` /
    ``__or__`` / ``__invert__`` (see predicates.py for the operator
    overloads on the abstract base).
    """

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool: ...


@runtime_checkable
class ReactivityCondition(Protocol):
    """Async, composable budget / gate check over a candidate fire.

    Returns True when the reactivity is *allowed* to fire — predicate
    matched AND no budget is exceeded AND domain is not disabled etc.
    Conditions read state (counters, recent fires); they MUST NOT increment
    budgets here. The registry increments after a successful fire so
    over-budget reactivities don't leave phantom counter rows.
    """

    async def allows(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool: ...


@runtime_checkable
class Reactivity(Protocol):
    """Protocol every Reactivity implements.

    The lifecycle methods (`propose` → `confirm` → `disable`) are owned by
    the registry; concrete Reactivities only own the runtime triple
    `predicate ∧ condition → fire`. This keeps Reactivities pure functions
    of an entry; lifecycle is bookkeeping.

    Implementations may be classes, dataclasses, or instances of a generic
    ``RuleReactivity`` factory. The Protocol is structural so all three
    pass ``isinstance(x, Reactivity)`` if they implement the members.
    """

    id: str
    name: str
    description: str
    scope: ReactivityScope
    predicate: ReactivityPredicate
    condition: ReactivityCondition

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult: ...


# ---------------------------------------------------------------------------
# Default implementations
# ---------------------------------------------------------------------------


@dataclass
class ReactivitySpec:
    """Serializable spec for a Reactivity, used by the propose / confirm
    lifecycle.

    Carries the same identity + intent fields a concrete Reactivity exposes,
    but no callable hooks — so it can round-trip through a ledger payload
    without losing fidelity. The registry maps ``id → concrete Reactivity``
    at boot; the ledger entry is the audit record.

    ``predicate_spec`` / ``condition_spec`` / ``action_spec`` are
    free-form dicts; a future "compile a Reactivity from chat" path will
    fill them with structured rules. For now they're documentation strings
    written by the Reactivity author at registration time.
    """

    id: str
    name: str
    description: str
    scope: ReactivityScope
    predicate_spec: dict[str, Any] = field(default_factory=dict)
    condition_spec: dict[str, Any] = field(default_factory=dict)
    action_spec: dict[str, Any] = field(default_factory=dict)


@dataclass
class _ReactivityStateRecord:
    """In-memory mirror of the ``reactivity_state`` row.

    Internal to the registry. Tracks the lifecycle for a single reactivity
    id so dispatch can skip ``state != "active"`` reactivities.
    """

    id: str
    state: ReactivityState
    proposed_by: str | None = None
    confirmed_by: UUID | None = None
    disabled_by: UUID | None = None
    disable_reason: str | None = None
    last_fired_at: datetime | None = None


__all__ = [
    "FiredAction",
    "Reactivity",
    "ReactivityCondition",
    "ReactivityContext",
    "ReactivityPredicate",
    "ReactivityResult",
    "ReactivityScope",
    "ReactivitySpec",
    "ReactivityState",
    "_ReactivityStateRecord",
]


def _reactivity_awaitable_check(value: Any) -> Awaitable[bool]:
    """Tiny helper: ensure a callable returned an Awaitable[bool].

    Predicate / Condition implementations are async; the abstract base
    classes wrap them so users can plug in plain callables in a pinch.
    Kept here (not in predicates.py) because both predicates and
    conditions need it.
    """
    if not hasattr(value, "__await__"):
        raise TypeError(
            f"expected an awaitable from a predicate/condition, got {type(value).__name__}"
        )
    return value
