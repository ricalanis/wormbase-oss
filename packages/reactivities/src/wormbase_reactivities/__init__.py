"""WormBase Reactivity Protocol — composable predicates, conditions, registry, runner.

Public API:

  * Protocol shapes — ``Reactivity``, ``ReactivityPredicate``,
    ``ReactivityCondition``, ``ReactivityContext``, ``ReactivityResult``,
    ``ReactivitySpec``, ``ReactivityScope``, ``ReactivityState``,
    ``FiredAction``.

  * Composable primitives — predicates ``EntryKind``, ``HasTopic``,
    ``HasDomain``, ``HasOwner``, ``SpeakerNotOwner``, ``PeriodicTick``
    (matches ``clock_tick`` entries at a given cadence; canonical class
    name in ``predicates.py`` is ``Periodic`` — re-exported here as
    ``PeriodicTick`` to avoid colliding with the wall-clock bucket
    Condition of the same name); conditions ``DailyBudget``,
    ``NotRecentlyFired``, ``DomainEnabled``, ``AlwaysAllow``,
    ``Periodic`` (wall-clock bucket gate used by
    ``KeepRatePublishReactivity``). All composable via ``__and__`` /
    ``__or__`` / ``__invert__``.

  * Registry + runner — ``ReactivityRegistry`` (lifecycle + budget +
    dispatch), ``ReactivityRunner`` (single async loop polling the ledger),
    ``ClockTickEmitter`` (parallel sibling daemon that writes periodic
    ``clock_tick`` ledger entries to drive time-based Reactivities; v2.B
    Phase 3 swap that decouples gap-escalation from new-gap traffic).

See ``protocol.py`` docstring for the design rationale and conceptual
sketches of how the existing five reactivity loops fit the Protocol.
"""

from __future__ import annotations

from wormbase_reactivities.clock_tick_emitter import ClockTickEmitter
from wormbase_reactivities.conditions import (
    AlwaysAllow,
    DailyBudget,
    DomainEnabled,
    LiveOnly,
    NotRecentlyFired,
    Periodic,
)
from wormbase_reactivities.conditions import And as ConditionAnd
from wormbase_reactivities.conditions import Not as ConditionNot
from wormbase_reactivities.conditions import Or as ConditionOr
from wormbase_reactivities.phenomenon_gaps import (
    DomainReferenceWithoutDomainReactivity,
    KpiReferenceWithoutKpiReactivity,
    ProcessReferenceWithoutProcessReactivity,
    RecurringActionWithoutReactivityReactivity,
)
from wormbase_reactivities.predicates import (
    And,
    EntryKind,
    HasDomain,
    HasOwner,
    HasTopic,
    Not,
    Or,
    ResolvedKept,
    SpeakerNotOwner,
)
from wormbase_reactivities.predicates import Periodic as PeriodicTick
from wormbase_reactivities.predicates_advanced import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DescribesProcessNotInLake,
    DescribesRecurringPattern,
    MentionsDomainNotInOntology,
    MentionsMetricNotInKpiTree,
)
from wormbase_reactivities.protocol import (
    FiredAction,
    Reactivity,
    ReactivityCondition,
    ReactivityContext,
    ReactivityPredicate,
    ReactivityResult,
    ReactivityScope,
    ReactivitySpec,
    ReactivityState,
)
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner
from wormbase_reactivities.statement_to_owner import (
    StatementToOwnerReactivity,
)

__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "AlwaysAllow",
    "And",
    "ClockTickEmitter",
    "ConditionAnd",
    "ConditionNot",
    "ConditionOr",
    "DailyBudget",
    "DescribesProcessNotInLake",
    "DescribesRecurringPattern",
    "DomainEnabled",
    "DomainReferenceWithoutDomainReactivity",
    "EntryKind",
    "FiredAction",
    "HasDomain",
    "HasOwner",
    "HasTopic",
    "KpiReferenceWithoutKpiReactivity",
    "LiveOnly",
    "MentionsDomainNotInOntology",
    "MentionsMetricNotInKpiTree",
    "Not",
    "NotRecentlyFired",
    "Or",
    "Periodic",
    "PeriodicTick",
    "ProcessReferenceWithoutProcessReactivity",
    "Reactivity",
    "ReactivityCondition",
    "ReactivityContext",
    "ReactivityPredicate",
    "ReactivityRegistry",
    "ReactivityResult",
    "ReactivityRunner",
    "ReactivityScope",
    "ReactivitySpec",
    "ReactivityState",
    "RecurringActionWithoutReactivityReactivity",
    "ResolvedKept",
    "SpeakerNotOwner",
    "StatementToOwnerReactivity",
]
