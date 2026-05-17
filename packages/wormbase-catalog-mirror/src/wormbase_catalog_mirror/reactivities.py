"""W5a Reactivities for catalog-mirror — initial import + drift detection.

Per Wave 1 plan §Task 5 and S5 spike findings: composes the existing W5a
predicate / condition algebra (``EntryKind``, ``NotRecentlyFired``,
``DomainEnabled``) with the existing ``ReactivityRegistry`` +
``ReactivityRunner``. No new orchestrator code.

Shape mirrors ``packages/lake-maintainer/src/wormbase_lake_maintainer/reactivities.py``:

* One Reactivity class per (CatalogSource × maintenance-method).
* ``fire`` calls the catalog source's discovery method, decides whether
  to emit, and writes the PEVR cycle via ``ledger.write``.
* ``predicate`` and ``condition`` are W5a primitives — no bespoke code.

Two Reactivities ship in Wave 1:

* ``CatalogImportReactivity`` — fires on ``source_profiled`` triggers; if
  no prior ``external_catalog_imported`` exists for ``source_id``, emits
  the initial-import PEVR cycle (plus the lineage / policy / metric
  companion entries).
* ``CatalogDriftReactivity`` — fires on the same refresh-trigger surface;
  re-discovers the catalog snapshot, compares its ``snapshot_hash``
  against the most-recent baseline, and emits
  ``external_catalog_drift_detected`` when the hash changes.

Both Reactivities are observation-only: verify_fn always passes, resolve_fn
always keeps. The ledger entry IS the side-effect.
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
    Reactivity,
    ReactivityCondition,
    ReactivityContext,
    ReactivityPredicate,
    ReactivityResult,
    ReactivityScope,
)

from .protocol import CatalogSource


# Entry kinds that should re-trigger catalog-mirror discovery. Mirrors
# lake-maintainer's _REFRESH_TRIGGER_KINDS surface so a single source-
# profiled (or downstream cascade) event re-evaluates both maintenance
# and catalog-mirror Reactivities consistently.
_REFRESH_TRIGGER_KINDS: tuple[str, ...] = (
    "source_profiled",
    "source_bronzed",
    "source_silvered",
    "source_golded",
    "external_catalog_imported",
)


def _refresh_trigger_predicate() -> ReactivityPredicate:
    """An Or() over the refresh-trigger entry kinds."""
    return Or(*(EntryKind(k) for k in _REFRESH_TRIGGER_KINDS))


def _has_prior_import(entries: list[dict[str, Any]], *, source_id: str) -> bool:
    """Return True if ``entries`` contains an ``external_catalog_imported``
    execute entry for ``source_id``.

    Walks the execute-row payload args. Used to short-circuit
    ``CatalogImportReactivity`` once the initial import has landed.
    """
    for row in entries:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        tool = payload.get("tool") or ""
        if "external_catalog_imported" not in tool:
            continue
        args = payload.get("args") or {}
        if args.get("source_id") == source_id:
            return True
    return False


def _latest_snapshot_hash(
    entries: list[dict[str, Any]], *, source_id: str,
) -> str | None:
    """Return the snapshot_hash of the most recent
    ``external_catalog_imported`` for ``source_id``, or ``None`` if absent.

    Walks the execute-row payload args; entries are scanned in their
    natural order (the ledger fetches them seq-ascending), so the last
    match wins.
    """
    latest: str | None = None
    for row in entries:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        tool = payload.get("tool") or ""
        if "external_catalog_imported" not in tool:
            continue
        args = payload.get("args") or {}
        if args.get("source_id") != source_id:
            continue
        h = args.get("snapshot_hash")
        if h:
            latest = str(h)
    return latest


async def _emit_pevr(
    *,
    ledger: Any,
    company_id: UUID,
    target_kind: str,
    tool: str,
    args: dict[str, Any],
    proposed_by: str = "catalog_mirror",
) -> None:
    """Emit one PEVR cycle for a catalog-mirror entry.

    Catalog-mirror writes are observation-only: verify_fn always passes,
    resolve_fn always keeps. Mirrors the lake-maintainer ``_emit_signal``
    pattern so the entries are byte-equivalent on shape across worms.
    """
    ref_id = str(args.get("source_id", ""))
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": target_kind,
            "ref_id": ref_id,
            "reason": f"catalog-mirror: {target_kind}",
            "proposed_by": proposed_by,
        },
        execute_fn=lambda: {
            "tool": tool,
            "args": args,
            "result_ref": ref_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "catalog_recorded", "ok": True}],
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
class CatalogImportReactivity:
    """Emits ``external_catalog_imported`` once per Source on first refresh trigger.

    Predicate: any refresh-trigger entry kind. Condition: ``DomainEnabled``
    only — the "fire once" semantics are enforced in ``fire`` by checking
    the ledger for a prior import entry, so a ``NotRecentlyFired`` gate
    would be redundant.

    On fire, also emits the lineage / policy / metric companion entries
    so downstream consumers (KPI proposer, /sources catalog tab) can
    project from one transactional cycle.
    """

    source_id: str
    domain_id: str
    catalog_source: CatalogSource
    secrets: dict[str, str] = field(default_factory=dict)
    scope: ReactivityScope = "company"

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = _refresh_trigger_predicate()
        self.condition = DomainEnabled()
        self.name = f"catalog-mirror.import:{self.source_id}"
        self.description = (
            f"Emits external_catalog_imported on first refresh trigger "
            f"for source_id={self.source_id}, plus lineage / policy / "
            f"metric companion entries."
        )

    @property
    def id(self) -> str:
        return f"catalog-mirror.import.{self.source_id}"

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        # Short-circuit if the initial import already landed: catalog-
        # mirror's "fire once" rule is enforced via the ledger itself.
        prior_entries = await context.ledger.fetch(context.company_id)
        if _has_prior_import(prior_entries, source_id=self.source_id):
            return ReactivityResult(fired=False, actions=[])

        handle = await self.catalog_source.authenticate(self.secrets)
        snap = await self.catalog_source.discover_catalog(handle)

        # Primary entry: external_catalog_imported
        await _emit_pevr(
            ledger=context.ledger,
            company_id=context.company_id,
            target_kind="external_catalog_imported",
            tool="emit_external_catalog_imported",
            args={
                "source_kind": self.catalog_source.kind,
                "source_id": self.source_id,
                "domain_id": self.domain_id,
                "snapshot_hash": snap.snapshot_hash,
                "table_count": len(snap.tables),
                "edge_count": len(snap.lineage.edges),
                "metric_count": len(snap.metrics),
                "import_mode": "initial",
            },
        )
        actions = [FiredAction(
            action_kind="external_catalog_imported", action_seqs=[],
        )]

        # Companion: external_lineage_imported (flat edge list)
        if snap.lineage.edges:
            await _emit_pevr(
                ledger=context.ledger,
                company_id=context.company_id,
                target_kind="external_lineage_imported",
                tool="emit_external_lineage_imported",
                args={
                    "source_id": self.source_id,
                    "edges": tuple(
                        (e.upstream, e.downstream)
                        for e in snap.lineage.edges
                    ),
                },
            )
            actions.append(FiredAction(
                action_kind="external_lineage_imported", action_seqs=[],
            ))

        # Companion: external_policy_imported (one per policy)
        for policy in snap.policies:
            await _emit_pevr(
                ledger=context.ledger,
                company_id=context.company_id,
                target_kind="external_policy_imported",
                tool="emit_external_policy_imported",
                args={
                    "source_id": self.source_id,
                    "policy_fqn": policy.name,
                    "policy_kind": policy.policy_kind,
                    "body": policy.body,
                    "applied_to": tuple(policy.applied_to),
                },
            )
            actions.append(FiredAction(
                action_kind="external_policy_imported", action_seqs=[],
            ))

        # Companion: external_metric_imported (one per metric)
        for metric in snap.metrics:
            await _emit_pevr(
                ledger=context.ledger,
                company_id=context.company_id,
                target_kind="external_metric_imported",
                tool="emit_external_metric_imported",
                args={
                    "source_id": self.source_id,
                    "name": metric.name,
                    "expression": metric.expression,
                    "time_grain": metric.time_grain,
                    "dimensions": tuple(metric.dimensions),
                    "description": metric.description,
                },
            )
            actions.append(FiredAction(
                action_kind="external_metric_imported", action_seqs=[],
            ))

        return ReactivityResult(fired=True, actions=actions)


@dataclass
class CatalogDriftReactivity:
    """Emits ``external_catalog_drift_detected`` when snapshot_hash changes.

    Predicate: refresh-trigger surface. Condition:
    ``NotRecentlyFired(novelty_key="catalog-mirror.drift.<source_id>",
    hours=drift_check_interval_hours) & DomainEnabled()`` — the novelty
    gate prevents drift-check spam when many trigger entries land in
    rapid succession (e.g. a cascade pass).

    On fire, the Reactivity re-discovers the snapshot and compares its
    hash to the most-recent baseline. v1 ships hash-only diff: the
    ``added_table_ids`` / ``removed_table_ids`` / ``changed_table_ids``
    fields are empty tuples. A column-level diff lands in Wave 1.1.
    """

    source_id: str
    domain_id: str
    catalog_source: CatalogSource
    secrets: dict[str, str] = field(default_factory=dict)
    drift_check_interval_hours: float = 24.0
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
                hours=self.drift_check_interval_hours,
            )
            & DomainEnabled()
        )
        self.name = f"catalog-mirror.drift:{self.source_id}"
        self.description = (
            f"Emits external_catalog_drift_detected when snapshot_hash "
            f"changes for source_id={self.source_id} (novelty window "
            f"{self.drift_check_interval_hours}h)."
        )

    @property
    def id(self) -> str:
        return f"catalog-mirror.drift.{self.source_id}"

    def _novelty_key(self) -> str:
        return f"catalog-mirror.drift.{self.source_id}"

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        prior_entries = await context.ledger.fetch(context.company_id)
        baseline_hash = _latest_snapshot_hash(
            prior_entries, source_id=self.source_id,
        )
        if baseline_hash is None:
            # Drift requires a prior import to baseline against. The
            # CatalogImportReactivity owns first-import; we no-op (and
            # don't charge novelty) until that landed.
            return ReactivityResult(
                fired=False, actions=[], novelty_key=self._novelty_key(),
            )

        handle = await self.catalog_source.authenticate(self.secrets)
        snap = await self.catalog_source.discover_catalog(handle)
        if snap.snapshot_hash == baseline_hash:
            return ReactivityResult(
                fired=False, actions=[], novelty_key=self._novelty_key(),
            )

        await _emit_pevr(
            ledger=context.ledger,
            company_id=context.company_id,
            target_kind="external_catalog_drift_detected",
            tool="emit_external_catalog_drift_detected",
            args={
                "source_id": self.source_id,
                "old_hash": baseline_hash,
                "new_hash": snap.snapshot_hash,
                # v1 ships hash-only diff; column-level delta is Wave 1.1.
                "added_table_ids": (),
                "removed_table_ids": (),
                "changed_table_ids": (),
            },
        )
        return ReactivityResult(
            fired=True,
            actions=[FiredAction(
                action_kind="external_catalog_drift_detected",
                action_seqs=[],
            )],
            novelty_key=self._novelty_key(),
        )


def make_catalog_mirror_reactivities(
    *,
    source_id: str,
    domain_id: str,
    catalog_source: CatalogSource,
    secrets: dict[str, str] | None = None,
    drift_check_interval_hours: float = 24.0,
) -> list[Reactivity]:
    """Return the two catalog-mirror Reactivities for one CatalogSource.

    Per Wave 1 plan Task 5: composes existing W5a primitives. The order
    is fixed — import first, drift second — so caller-side telemetry
    can rely on the registration shape.

    ``ledger`` is intentionally NOT a factory parameter: each Reactivity
    receives the ledger via ``ReactivityContext`` at dispatch time,
    matching the lake-maintainer pattern and keeping the factory pure.
    """
    secrets_dict = dict(secrets or {})
    return [
        CatalogImportReactivity(
            source_id=source_id,
            domain_id=domain_id,
            catalog_source=catalog_source,
            secrets=secrets_dict,
        ),
        CatalogDriftReactivity(
            source_id=source_id,
            domain_id=domain_id,
            catalog_source=catalog_source,
            secrets=secrets_dict,
            drift_check_interval_hours=drift_check_interval_hours,
        ),
    ]


__all__ = [
    "CatalogDriftReactivity",
    "CatalogImportReactivity",
    "make_catalog_mirror_reactivities",
]
