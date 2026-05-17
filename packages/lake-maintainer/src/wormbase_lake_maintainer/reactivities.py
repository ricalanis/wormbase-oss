"""Maintenance Reactivities — one class per (Source x maintenance_method).

Per spike section 8 C6: each maintenance method composes into a Reactivity
using W5a's existing predicate/condition algebra. The factory in
``factory.py`` produces an instance per Source on connect; the existing
``ReactivityRegistry`` registers them; the existing ``ReactivityRunner``
dispatches them. **No new orchestrator loop.**

Each class follows the same shape:

    id           = "<method>_<source_short_id>"
    predicate    = composed from W5a's EntryKind / Or / And / etc.
    condition    = composed from W5a's NotRecentlyFired / DailyBudget / DomainEnabled
    fire(entry, ctx) = call source.<method>() and emit a PEVR cycle
                       on the appropriate edge

The fire() emits an audit-only PEVR cycle (``emit_source_*_signaled``);
it does NOT mutate source state. State updates (e.g. setting
``baseline_schema_hash``) are the next-wave concern.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from wormbase_reactivities.conditions import DomainEnabled, NotRecentlyFired
from wormbase_reactivities.predicates import EntryKind, Or
from wormbase_reactivities.protocol import (
    FiredAction,
    ReactivityCondition,
    ReactivityContext,
    ReactivityPredicate,
    ReactivityResult,
    ReactivityScope,
)


# Entry kinds the maintenance Reactivities react to. Any of them is a
# signal that the maintainer should re-evaluate at least one
# MaintainableSource. EntryKind already handles the "channel_adapter."
# tool-prefix variants, so we only list the canonical short form.
_REFRESH_TRIGGER_KINDS: tuple[str, ...] = (
    "source_profiled",
    "source_bronzed",
    "source_silvered",
    "source_golded",
    "chat_received",
    "data_product_published",
    "notebook_published",
    "kpi_confirmed",
)


def _refresh_trigger_predicate() -> ReactivityPredicate:
    """An Or() over every trigger kind."""
    return Or(*(EntryKind(k) for k in _REFRESH_TRIGGER_KINDS))


async def _emit_signal(
    *,
    ledger: Any,
    company_id: UUID,
    target_kind: str,
    tool: str,
    args: dict[str, Any],
    proposed_by: str = "lake_maintainer",
) -> None:
    """Emit one PEVR cycle for a maintenance signal.

    Maintenance signals are observation-only: verify_fn always passes,
    resolve_fn always keeps. Cycle exists to land the entry with full
    provenance per the PEVR contract.
    """
    ref_id = args.get("source_id", "")
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": target_kind,
            "ref_id": ref_id,
            "reason": f"lake-maintainer signal: {target_kind}",
            "proposed_by": proposed_by,
        },
        execute_fn=lambda: {
            "tool": tool,
            "args": args,
            "result_ref": ref_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "signal_recorded", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": f"{target_kind} observed",
        },
        timestamp=datetime.now(UTC),
        quadrant="active_deterministic",
    )


@dataclass
class StalenessSignalReactivity:
    """Fires when source.staleness_signal() returns stale=True.

    Predicate: any refresh trigger kind. Condition: NotRecentlyFired
    keyed on staleness_<source_id> with a 1-hour novelty window.
    Fire: call source.staleness_signal() and emit
    emit_source_staleness_signaled if stale=True.
    """

    source: Any  # MaintainableSource
    novelty_hours: float = 1.0
    scope: ReactivityScope = "company"

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = _refresh_trigger_predicate()
        self.condition = (
            NotRecentlyFired(
                novelty_key=self._novelty_key(),
                hours=self.novelty_hours,
            )
            & DomainEnabled()
        )
        self.name = f"staleness:{self.source.id}"
        self.description = (
            f"Emits emit_source_staleness_signaled when "
            f"source.staleness_signal() returns stale=True for "
            f"source_id={self.source.id}."
        )

    @property
    def id(self) -> str:
        return f"staleness_{self.source.id}"

    def _novelty_key(self) -> str:
        return f"staleness_{self.source.id}"

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        report = await self.source.staleness_signal()
        if not report.stale:
            return ReactivityResult(
                fired=False, actions=[], novelty_key=self._novelty_key(),
            )
        await _emit_signal(
            ledger=context.ledger,
            company_id=context.company_id,
            target_kind="source_staleness_signaled",
            tool="emit_source_staleness_signaled",
            args={
                "source_id": str(self.source.id),
                "family": self.source.family,
                "last_seen": (
                    report.last_seen.isoformat() if report.last_seen else None
                ),
                "sla_hours": report.sla_hours,
            },
        )
        return ReactivityResult(
            fired=True,
            actions=[
                FiredAction(
                    action_kind="source_staleness_signaled",
                    action_seqs=[],
                ),
            ],
            novelty_key=self._novelty_key(),
            budget_used={},
        )


@dataclass
class DriftDetectorReactivity:
    """Fires when source.detect_drift() returns drifted=True."""

    source: Any
    novelty_hours: float = 1.0
    scope: ReactivityScope = "company"

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = _refresh_trigger_predicate()
        self.condition = (
            NotRecentlyFired(novelty_key=self._novelty_key(), hours=self.novelty_hours)
            & DomainEnabled()
        )
        self.name = f"drift:{self.source.id}"
        self.description = (
            f"Emits emit_source_drift_detected when "
            f"source.detect_drift() returns drifted=True for "
            f"source_id={self.source.id}."
        )

    @property
    def id(self) -> str:
        return f"drift_{self.source.id}"

    def _novelty_key(self) -> str:
        return f"drift_{self.source.id}"

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        report = await self.source.detect_drift()
        if not report.drifted:
            return ReactivityResult(
                fired=False, actions=[], novelty_key=self._novelty_key(),
            )
        # schema_hash is str (hex) per the plan's pre-execution corrections;
        # bytes-typed legacy values are also tolerated for defensive correctness.
        def _h(v: Any) -> str | None:
            if v is None:
                return None
            return v.hex() if isinstance(v, (bytes, bytearray)) else str(v)
        await _emit_signal(
            ledger=context.ledger,
            company_id=context.company_id,
            target_kind="source_drift_detected",
            tool="emit_source_drift_detected",
            args={
                "source_id": str(self.source.id),
                "family": self.source.family,
                "reason": report.reason,
                "baseline_hash": _h(report.baseline_hash),
                "current_hash": _h(report.current_hash),
            },
        )
        return ReactivityResult(
            fired=True,
            actions=[FiredAction(
                action_kind="source_drift_detected",
                action_seqs=[],
            )],
            novelty_key=self._novelty_key(),
        )


@dataclass
class ClassificationRefreshReactivity:
    """Fires when source.refresh_classification() returns updated=True."""

    source: Any
    novelty_hours: float = 6.0  # longer novelty: classification changes are slower
    scope: ReactivityScope = "company"

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = _refresh_trigger_predicate()
        self.condition = (
            NotRecentlyFired(novelty_key=self._novelty_key(), hours=self.novelty_hours)
            & DomainEnabled()
        )
        self.name = f"classification:{self.source.id}"
        self.description = (
            f"Emits emit_source_classification_refreshed when "
            f"source.refresh_classification() returns updated=True for "
            f"source_id={self.source.id}."
        )

    @property
    def id(self) -> str:
        return f"classification_{self.source.id}"

    def _novelty_key(self) -> str:
        return f"classification_{self.source.id}"

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        report = await self.source.refresh_classification()
        if not report.updated:
            return ReactivityResult(
                fired=False, actions=[], novelty_key=self._novelty_key(),
            )
        await _emit_signal(
            ledger=context.ledger,
            company_id=context.company_id,
            target_kind="source_classification_refreshed",
            tool="emit_source_classification_refreshed",
            args={
                "source_id": str(self.source.id),
                "family": self.source.family,
                "classification": report.classification,
                "previous_classification": report.previous_classification,
                "reason": report.reason,
            },
        )
        return ReactivityResult(
            fired=True,
            actions=[FiredAction(
                action_kind="source_classification_refreshed",
                action_seqs=[],
            )],
            novelty_key=self._novelty_key(),
        )


@dataclass
class LineageHealthReactivity:
    """Fires when source.lineage_health() returns healthy=False with broken edges."""

    source: Any
    novelty_hours: float = 4.0
    scope: ReactivityScope = "company"

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = _refresh_trigger_predicate()
        self.condition = (
            NotRecentlyFired(novelty_key=self._novelty_key(), hours=self.novelty_hours)
            & DomainEnabled()
        )
        self.name = f"lineage:{self.source.id}"
        self.description = (
            f"Emits emit_source_lineage_break_detected when "
            f"source.lineage_health() returns healthy=False for "
            f"source_id={self.source.id}."
        )

    @property
    def id(self) -> str:
        return f"lineage_{self.source.id}"

    def _novelty_key(self) -> str:
        return f"lineage_{self.source.id}"

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        report = await self.source.lineage_health()
        if report.healthy:
            return ReactivityResult(
                fired=False, actions=[], novelty_key=self._novelty_key(),
            )
        await _emit_signal(
            ledger=context.ledger,
            company_id=context.company_id,
            target_kind="source_lineage_break_detected",
            tool="emit_source_lineage_break_detected",
            args={
                "source_id": str(self.source.id),
                "family": self.source.family,
                "broken_edges": [
                    {
                        "upstream_kind": e.upstream_kind,
                        "upstream_id": e.upstream_id,
                        "downstream_kind": e.downstream_kind,
                        "downstream_id": e.downstream_id,
                        "reason": e.reason,
                    }
                    for e in report.broken_edges
                ],
            },
        )
        return ReactivityResult(
            fired=True,
            actions=[FiredAction(
                action_kind="source_lineage_break_detected",
                action_seqs=[],
            )],
            novelty_key=self._novelty_key(),
        )


__all__ = [
    "ClassificationRefreshReactivity",
    "DriftDetectorReactivity",
    "LineageHealthReactivity",
    "StalenessSignalReactivity",
]
