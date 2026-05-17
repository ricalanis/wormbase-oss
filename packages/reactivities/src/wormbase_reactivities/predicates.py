"""Composable predicates for the Reactivity Protocol.

Each predicate is an async, composable matcher over a ledger entry. The
abstract base ``_PredicateBase`` wires the ``__and__`` / ``__or__`` /
``__invert__`` operator overloads so usage is ergonomic:

    predicate = EntryKind("chat_received") & HasTopic() & SpeakerNotOwner()

The composed object is itself a predicate (``_AndPredicate`` instance), so
it can be combined further or assigned directly to a Reactivity.

Why async? Future predicates will hit the inference router for semantic
matching (e.g. ``HasTopic`` may invoke an embedding lookup against the
org's ontology). Forcing sync now would force a rewrite the day a
predicate needs I/O. The cost of async-by-default is a single ``await`` at
each call site; the benefit is uniform composition across all predicates.

Why no shortcut for "ledger entry is a chat message"? Because composability
is the load-bearing feature. We export the primitive ``EntryKind("chat_received")``
and let users build up. A library of ``Slack``, ``ChatFromBob``, etc. helpers
would invite cargo-cult one-offs that bypass composition.

The ``HasTopic`` / ``HasDomain`` / ``HasOwner`` predicates inspect the
entry's ``payload.args`` for relevant fields. The exact field names match
what the channel-adapter / process_extractor wires write today, so existing
ledger entries are matchable without payload changes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from wormbase_reactivities.protocol import (
    ReactivityContext,
    ReactivityPredicate,
)

# A thin async-callable shape — predicate implementations may be wrapped
# from plain callables for terse local use. The base class adapts both.
PredicateFn = Callable[
    [dict[str, Any], ReactivityContext],
    Awaitable[bool],
]


class _PredicateBase:
    """Mixin that wires the composition operators on ReactivityPredicate.

    Subclasses implement ``async def match(self, entry, context) -> bool``;
    the operators here build ``And``/``Or``/``Not`` instances. We use a
    base class (not a Protocol) for this so the operator dunders live in
    one place.
    """

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        raise NotImplementedError

    def __and__(self, other: ReactivityPredicate) -> "And":
        return And(self, other)

    def __or__(self, other: ReactivityPredicate) -> "Or":
        return Or(self, other)

    def __invert__(self) -> "Not":
        return Not(self)


@dataclass
class EntryKind(_PredicateBase):
    """Match entries whose ``kind`` (envelope or wrapped tool) equals ``kind``.

    Two slots match for compatibility with the existing ledger shape:

    * The envelope ``kind`` itself (e.g. "execute", "propose", "verify",
      "resolve") — useful when a Reactivity wants to react to canonical
      entries, not domain-specific tools.

    * For ``execute`` envelopes, ``payload.tool`` (e.g.
      "channel_adapter.emit_chat_received" → matches "chat_received"
      after stripping the prefix). This is the common case: most
      Reactivities care about tool-level events, not the
      propose/execute/verify/resolve scaffolding.

    The double-match keeps callers honest: ``EntryKind("chat_received")``
    matches both forms uniformly, no surprise for the predicate author.
    """

    kind: str

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        envelope_kind = entry.get("kind")
        if envelope_kind == self.kind:
            return True
        if envelope_kind != "execute":
            return False
        payload = entry.get("payload") or {}
        tool = payload.get("tool")
        if not tool:
            return False
        # Tool names look like "channel_adapter.emit_chat_received" or
        # plain "emit_person_proposed". We match on the trailing chunk
        # after the optional ``emit_`` prefix.
        if tool == self.kind:
            return True
        if tool.endswith(f".emit_{self.kind}"):
            return True
        if tool == f"emit_{self.kind}":
            return True
        return False


class _ArgsPredicate(_PredicateBase):
    """Common base for predicates that inspect ``payload.args`` of execute rows.

    Returns False fast for non-execute envelopes so subclasses don't have
    to duplicate that guard. Subclasses implement ``_check(args)``.
    """

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        if entry.get("kind") != "execute":
            return False
        payload = entry.get("payload") or {}
        args = payload.get("args") or {}
        return await self._check(args, entry, context)

    async def _check(
        self,
        args: dict[str, Any],
        entry: dict[str, Any],
        context: ReactivityContext,
    ) -> bool:
        raise NotImplementedError


class HasTopic(_ArgsPredicate):
    """Match when the entry carries a non-empty topic / topic_id.

    Conventions vary across writers — channel-adapter inbound entries
    don't carry topics today, but the W5.A2 statement-to-owner reactivity
    will inject ``topic`` into the args before writing. We accept
    ``topic`` (string), ``topic_id`` (UUID-as-str), or ``topic_kind``
    (``kpi``/``source``/``domain``/``process``) as evidence.

    To avoid a circular dep on worm-core's ``extract_topic``, this
    predicate is intentionally pure: callers run extraction upstream and
    inject the result. Future Reactivities can add an ``ExtractedTopic``
    predicate that calls into worm-core via lazy import.
    """

    async def _check(
        self,
        args: dict[str, Any],
        entry: dict[str, Any],
        context: ReactivityContext,
    ) -> bool:
        for key in ("topic", "topic_id", "topic_kind"):
            v = args.get(key)
            if v:
                return True
        return False


class HasDomain(_ArgsPredicate):
    """Match when the entry carries a non-empty ``domain`` or ``domain_id``."""

    async def _check(
        self,
        args: dict[str, Any],
        entry: dict[str, Any],
        context: ReactivityContext,
    ) -> bool:
        return bool(args.get("domain") or args.get("domain_id"))


class HasOwner(_ArgsPredicate):
    """Match when the entry carries a non-empty ``owner_id`` or ``owner_person``.

    Used by Reactivities that route messages to resource owners. The
    canonical writer is ``StatementToOwnerReactivity`` upstream; this
    predicate is the gate that says "owner has been resolved, fire is
    legit".
    """

    async def _check(
        self,
        args: dict[str, Any],
        entry: dict[str, Any],
        context: ReactivityContext,
    ) -> bool:
        return bool(
            args.get("owner_id")
            or args.get("owner_person")
            or args.get("owner_person_id")
        )


class SpeakerNotOwner(_ArgsPredicate):
    """Match when the entry's ``sender_person`` is NOT the resource owner.

    Self-statements ("I'll fix the churn report myself") shouldn't
    interrupt the owner with a DM about their own remark. This predicate
    short-circuits when either the sender or the owner is missing —
    return False so the reactivity doesn't fire on incomplete data.
    """

    async def _check(
        self,
        args: dict[str, Any],
        entry: dict[str, Any],
        context: ReactivityContext,
    ) -> bool:
        sender = args.get("sender_person") or args.get("sender_person_id")
        owner = (
            args.get("owner_id")
            or args.get("owner_person")
            or args.get("owner_person_id")
        )
        if not sender or not owner:
            return False
        return str(sender) != str(owner)


class ResolvedKept(_ArgsPredicate):
    """Match ``experiment_resolved`` execute entries whose outcome is ``keep``.

    Conceptually ``EntryKind("experiment_resolved") & (args.outcome == "keep")``.
    We don't have a generic ``PayloadFieldEquals`` primitive yet, and adding
    one for a single use case would broaden the surface unnecessarily — the
    autoresearch ledger only emits ``outcome ∈ {keep, discard}`` from
    ``emit_experiment_resolved``, so this small dedicated predicate is the
    cleaner read.

    Used by ``LessonExtractionReactivity`` (wormbase-research-loop) to fire
    only on kept experiments. Future waves (decision-worm, process-worm)
    that want to predicate on kept experiments will reuse this directly.

    Note on payload shape: ``experiment_resolved`` rows are written as
    ``execute`` envelopes with ``payload.tool == "emit_experiment_resolved"``
    and ``payload.args.outcome ∈ {keep, discard}``. We rely on
    ``EntryKind("experiment_resolved")`` semantics (which match the
    ``emit_<kind>`` trailing chunk) for the kind gate, and inherit the
    args-extraction guard from ``_ArgsPredicate``.
    """

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        if not await EntryKind("experiment_resolved").match(entry, context):
            return False
        return await super().match(entry, context)

    async def _check(
        self,
        args: dict[str, Any],
        entry: dict[str, Any],
        context: ReactivityContext,
    ) -> bool:
        return args.get("outcome") == "keep"


@dataclass(frozen=True)
class Periodic(_PredicateBase):
    """Match ``clock_tick`` entries whose ``tick_interval_s`` equals ``every_seconds``.

    Drives time-based Reactivities — pairs with ``ClockTickEmitter`` in
    ``wormbase_reactivities.clock_tick_emitter``. v2.B Phase 3 (2026-05-12)
    swaps axis 4 (``semantic_gap_to_escalation``) from
    ``EntryKind("semantic_gap_proposed")`` to
    ``Periodic(every_seconds=3600)`` so the Reactivity fires on a real
    cadence regardless of new-gap traffic. A freshly-installed worm with
    pre-existing gaps can now escalate them at the next tick, instead of
    waiting for a second gap to land.

    Conceptually equivalent to
    ``EntryKind("clock_tick") & ArgsEq("tick_interval_s", every_seconds)``,
    but expressed as a single predicate for readability and to avoid
    introducing a generic ``ArgsEq`` primitive for a single use case.

    Note on name collision: ``wormbase_reactivities.conditions`` also has
    a class named ``Periodic`` — that one is a **Condition** (gates
    firing by wall-clock bucket; used by ``KeepRatePublishReactivity``).
    This one is a **Predicate** (matches an entry's kind + args). They
    are different Protocols. The package surface (``__init__.py``)
    re-exports this predicate as ``Periodic`` and aliases the condition
    to ``ConditionPeriodic`` so the two can be imported side-by-side
    when needed.

    ``clock_tick`` entries are written by the emitter at the canonical
    envelope level (``entry["kind"] == "clock_tick"``), not as
    ``execute`` envelopes wrapping a tool call — so we match the
    envelope kind + read ``tick_interval_s`` directly from the payload
    (no ``args`` indirection). The emitter constructs the payload from
    ``ClockTickPayload(tick_interval_s=..., sequence_number=...)`` and
    writes via the canonical PEVR primitive; the runner sees a series
    of ``propose`` / ``execute`` / ``verify`` / ``resolve`` rows. The
    predicate matches on the **execute** envelope of the cycle (where
    ``payload["tool"] == "emit_clock_tick"`` and
    ``payload["args"]["tick_interval_s"] == every_seconds``) so the
    runner dispatches the fire on the same canonical row pattern other
    Reactivities use.
    """

    every_seconds: int

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        if entry.get("kind") != "execute":
            return False
        payload = entry.get("payload") or {}
        if not isinstance(payload, dict):
            return False
        if payload.get("tool") != "emit_clock_tick":
            return False
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            return False
        try:
            return int(args.get("tick_interval_s", -1)) == int(self.every_seconds)
        except (TypeError, ValueError):
            return False


@dataclass
class And(_PredicateBase):
    """Logical AND over an arbitrary number of predicates.

    Short-circuits at the first False — predicates with cheap checks
    should be passed first. Empty list returns True (vacuously true) so
    callers can build up an And iteratively without a special case for
    the empty start state.
    """

    predicates: tuple[ReactivityPredicate, ...]

    def __init__(self, *predicates: ReactivityPredicate) -> None:
        self.predicates = predicates

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        for p in self.predicates:
            if not await p.match(entry, context):
                return False
        return True


@dataclass
class Or(_PredicateBase):
    """Logical OR over an arbitrary number of predicates.

    Short-circuits at the first True. Empty list returns False (vacuously
    false).
    """

    predicates: tuple[ReactivityPredicate, ...]

    def __init__(self, *predicates: ReactivityPredicate) -> None:
        self.predicates = predicates

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        for p in self.predicates:
            if await p.match(entry, context):
                return True
        return False


@dataclass
class Not(_PredicateBase):
    """Logical negation of a single predicate.

    Implemented as a dataclass for ``repr()`` clarity — printing a
    composed predicate at debug time produces ``Not(EntryKind('chat_received'))``,
    which reads like the source.
    """

    predicate: ReactivityPredicate

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        return not await self.predicate.match(entry, context)


__all__ = [
    "And",
    "EntryKind",
    "HasDomain",
    "HasOwner",
    "HasTopic",
    "Not",
    "Or",
    "Periodic",
    "PredicateFn",
    "ResolvedKept",
    "SpeakerNotOwner",
]
