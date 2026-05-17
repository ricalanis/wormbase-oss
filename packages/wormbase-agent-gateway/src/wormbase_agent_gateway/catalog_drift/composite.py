"""L2 catalog-drift detection — composite via LakeLoopComposite[T].

:func:`make_composite_catalog_drift_service` composes any subset of
the 3 strategies (TableSet, ColumnSet, ColumnType) via Optional-Effect
Injection (doctrine case 16 — **fifth lake-side axis built on top of
:class:`LakeLoopComposite` from day one**, after L5 case 12, L6 case
13, L8 case 14, L1 case 15). Each strategy slot is independently
``None``-able; missing slots short-circuit to empty proposal lists
and increment the composite's no-op telemetry counter.

The factory returns a :class:`LakeLoopComposite` parameterised over
:class:`ProposedCatalogDrift` — the abstraction does ALL the heavy
lifting. Per spec §4.7, this is **~12 LOC of factory code** —
continuing the downward LOC trend across day-one consumers
(L5=16, L6=15, L8=14, L1=11, L2≈12).

Doctrine case 16 framing extends cases 12-15 to an eighth L-axis
Compounding service with the same Optional-Effect Injection contract.
L2 introduces ZERO new cross-axis Protocol CHAINS (the L4→L3 /
L6→L5 / L8→L5 sense). It DOES introduce 1 new lightweight Reader
Protocol (:class:`CatalogSnapshotReader`), but it reads catalog-mirror
substrate (``external_catalog_imported`` entries), not a peer L-axis
projection — see :mod:`.protocol` for the doctrine clarification.

Identity key: ``drift_id`` (deterministic hash of
``(source_id, table_id, column, drift_kind, before, after)``; merges
across strategies on the same logical drift). Rationale: per spec
§4.7, L2 wants **merge-across-strategy** dedup behaviour (mirrors L5
+ L8 merge-on-pair; diverges from L6 + L1 keep-separate-by-strategy).
Reason: if two strategies somehow propose the same logical drift (e.g.
TableSet and a future MetadataHash strategy), the admin queue should
surface ONE row with both reasonings folded.
"""
from __future__ import annotations

from wormbase_agent_gateway.lake_loop import LakeLoopComposite

from .protocol import ProposedCatalogDrift
from .strategies import (
    ColumnSetDriftStrategy,
    ColumnTypeDriftStrategy,
    TableSetDriftStrategy,
)

__all__ = ["make_composite_catalog_drift_service"]


def make_composite_catalog_drift_service(
    *,
    table_set: TableSetDriftStrategy | None = None,
    column_set: ColumnSetDriftStrategy | None = None,
    column_type: ColumnTypeDriftStrategy | None = None,
    min_confidence: float | None = None,
) -> LakeLoopComposite[ProposedCatalogDrift]:
    """Compose the 3 L2 catalog-drift strategies via :class:`LakeLoopComposite`.

    Optional-Effect Injection (doctrine case 16 — fifth lake-side axis
    built on top of :class:`LakeLoopComposite` from day one). Each slot
    independently ``None``-able; the returned composite still
    implements :class:`.protocol.CatalogDriftStrategy` and returns an
    empty proposal list when every strategy is ``None``.

    Strategy execution order: ``table_set → column_set → column_type``.
    Order is pinned by tests for replay stability — table-level drift
    fires first because it carries the strongest, least-ambiguous
    signal; column-level diffs come next; type diffs last.

    Identity key is ``drift_id`` — the deterministic hash of the
    ``(source_id, table_id, column, drift_kind, before, after)`` tuple.
    Two strategies proposing the same logical drift collide on the
    same id and merge into one projection row (per spec §4.7;
    mirrors L5+L8 merge-on-pair, diverges from L6+L1).

    ``min_confidence``: optional promotion-time floor. When set,
    proposals with ``confidence < min_confidence`` are dropped
    POST-merge by the underlying :class:`LakeLoopComposite`. Wired
    from ``WORMBASE_CATALOG_DRIFT_MIN_CONFIDENCE`` at the worm-core
    construction site (L2 floor default 0.7 per spec §4.7).
    ``None`` (default) = no filtering (back-compat for tests that
    don't supply a knob).

    The factory body is ~12 LOC by design — see the module docstring
    for the validation framing. No custom composite class is needed.
    """
    return LakeLoopComposite[ProposedCatalogDrift](
        case_name="catalog_drift_inference",
        strategies={
            "table_set": table_set,
            "column_set": column_set,
            "column_type": column_type,
        },
        propose_method="propose",
        identity_key=lambda p: p.drift_id,
        proposals_counter_name="drifts_proposed",
        min_confidence=min_confidence,
    )
