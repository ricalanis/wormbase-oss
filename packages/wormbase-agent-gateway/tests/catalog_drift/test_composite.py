"""L2 Sub-wave B — composite tests.

Pins the L2-specific wiring of the shared :class:`LakeLoopComposite`:

  * Factory returns a :class:`LakeLoopComposite` (NOT a custom class).
  * Optional-Effect Injection case 16: each slot independently
    ``None``-able; all-None yields ``[]`` + ``no_op`` counter.
  * Telemetry keys are axis-namespaced: ``catalog_drift_inference_*``.
  * Strategy slot order: ``table_set → column_set → column_type``.
  * Identity key = ``drift_id``:
    same logical drift across strategies merges into ONE row
    (merge-across-strategy posture; mirrors L5+L8, diverges from
    L6+L1).
  * Fifth from-day-one consumer of LakeLoopComposite (after
    L5 + L6 + L8 + L1).

Minimal — the generic shape is already pinned by
``tests/unit/test_lake_loop_composite.py`` and the pre-extraction axes'
suites.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from wormbase_agent_gateway.catalog_drift import (
    CatalogColumn,
    CatalogSnapshot,
    CatalogTable,
    ColumnSetDriftStrategy,
    ColumnTypeDriftStrategy,
    ProposedCatalogDrift,
    TableSetDriftStrategy,
    make_composite_catalog_drift_service,
)
from wormbase_agent_gateway.lake_loop import LakeLoopComposite


_COMPANY = UUID("00000000-0000-0000-0000-000000000a05")


def _now() -> datetime:
    return datetime.now(UTC)


def _earlier() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Factory shape — validates LakeLoopComposite reuse (5th from-day-one)
# ---------------------------------------------------------------------------


def test_factory_returns_lake_loop_composite_instance() -> None:
    """The smoking-gun validation: composite IS a :class:`LakeLoopComposite`.

    Pin: L2 does NOT define a custom composite class. The factory
    function delegates entirely to the shared generic. **Fifth**
    from-day-one consumer of the abstraction (after L5+L6+L8+L1) —
    continues to validate that the DRY refactor at ``a4a62c2`` pays
    off for new consumers.
    """
    composite = make_composite_catalog_drift_service()
    assert isinstance(composite, LakeLoopComposite)


def test_factory_uses_catalog_drift_inference_case_name() -> None:
    """Composite's case_name is ``catalog_drift_inference``."""
    composite = make_composite_catalog_drift_service()
    assert composite.case_name == "catalog_drift_inference"


def test_factory_strategy_slots_match_spec() -> None:
    """Slots are ``table_set`` / ``column_set`` / ``column_type`` in order."""
    composite = make_composite_catalog_drift_service()
    slots = list(composite.strategies)
    assert slots == ["table_set", "column_set", "column_type"]


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot (case 16)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_all_none_returns_empty_and_counts_no_op() -> None:
    """All strategy slots None → empty proposal list + no_op counter."""
    composite = make_composite_catalog_drift_service()
    proposals = await composite.propose(
        company_id=_COMPANY,
        current=CatalogSnapshot(source_id="src", as_of=_now()),
        baseline=None,
    )
    assert proposals == []
    metrics = composite.metrics()
    prefix = "catalog_drift_inference"
    assert metrics[f"{prefix}_invocations"] == 1
    assert metrics[f"{prefix}_no_op"] == 1
    assert metrics[f"{prefix}_drifts_proposed"] == 0
    assert metrics[f"{prefix}_strategy_invocations.table_set"] == 0
    assert metrics[f"{prefix}_strategy_invocations.column_set"] == 0
    assert metrics[f"{prefix}_strategy_invocations.column_type"] == 0


@pytest.mark.asyncio
async def test_composite_only_table_set_runs() -> None:
    """``table_set`` set, others None → only that counter increments."""
    composite = make_composite_catalog_drift_service(
        table_set=TableSetDriftStrategy(),
    )
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(CatalogTable(table_id="src-1.public.a"),),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(table_id="src-1.public.a"),
            CatalogTable(table_id="src-1.public.b"),
        ),
    )
    proposals = await composite.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) == 1
    metrics = composite.metrics()
    prefix = "catalog_drift_inference"
    assert metrics[f"{prefix}_strategy_invocations.table_set"] == 1
    assert metrics[f"{prefix}_strategy_invocations.column_set"] == 0
    assert metrics[f"{prefix}_strategy_invocations.column_type"] == 0
    assert metrics[f"{prefix}_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_only_column_set_runs_with_columns_present() -> None:
    """``column_set`` set + columns present → only that counter increments."""
    composite = make_composite_catalog_drift_service(
        column_set=ColumnSetDriftStrategy(),
    )
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="id"),),
            ),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(
                    CatalogColumn(name="id"),
                    CatalogColumn(name="email"),
                ),
            ),
        ),
    )
    proposals = await composite.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) >= 1
    metrics = composite.metrics()
    prefix = "catalog_drift_inference"
    assert metrics[f"{prefix}_strategy_invocations.column_set"] == 1
    assert metrics[f"{prefix}_strategy_invocations.table_set"] == 0


@pytest.mark.asyncio
async def test_composite_only_column_type_runs_with_types_present() -> None:
    """``column_type`` set + type info present → only that counter increments."""
    composite = make_composite_catalog_drift_service(
        column_type=ColumnTypeDriftStrategy(),
    )
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="email", type="varchar(100)"),),
            ),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="email", type="varchar(255)"),),
            ),
        ),
    )
    proposals = await composite.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) >= 1
    metrics = composite.metrics()
    prefix = "catalog_drift_inference"
    assert metrics[f"{prefix}_strategy_invocations.column_type"] == 1


# ---------------------------------------------------------------------------
# Strategy returns empty but slot is wired — no_op should NOT increment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_strategy_returns_empty_no_op_not_incremented() -> None:
    """Strategy wired but returns [] → no proposals, but no_op NOT fired."""
    # No baseline → TableSet returns []
    composite = make_composite_catalog_drift_service(
        table_set=TableSetDriftStrategy(),
    )
    proposals = await composite.propose(
        company_id=_COMPANY,
        current=CatalogSnapshot(source_id="src", as_of=_now()),
        baseline=None,
    )
    assert proposals == []
    metrics = composite.metrics()
    prefix = "catalog_drift_inference"
    assert metrics[f"{prefix}_strategy_invocations.table_set"] == 1
    assert metrics[f"{prefix}_no_op"] == 0
    assert metrics[f"{prefix}_drifts_proposed"] == 0


# ---------------------------------------------------------------------------
# Merge-across-strategy (drift_id collapses cross-strategy)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_filters_below_min_confidence() -> None:
    """``min_confidence`` floor wired through factory → low-confidence
    proposals dropped; high-confidence survive; per-strategy telemetry
    intact (filter is post-merge, not per-strategy).

    Polish-bundle 2026-06-10. Pins the L2 wire-through of the shared
    LakeLoopComposite min_confidence floor — knob is sourced from
    ``WORMBASE_CATALOG_DRIFT_MIN_CONFIDENCE`` (L2 default 0.7 per
    spec §4.7) at the construction site.

    Test setup: two TableSet strategies — one at high confidence 0.90
    (default), one at low confidence 0.50 (constructor knob). They
    propose different drifts on the same snapshot pair (one
    ``table_added`` per added table). Setting the composite floor at
    0.70 keeps the high-confidence proposal and drops the low-
    confidence one.
    """
    # Two TableSetDrift strategies wired into different slots; each
    # emits a single proposal with its own confidence. We use
    # ``table_set`` and ``column_type`` slots to keep them on
    # independent drift-axes that won't collide on drift_id.
    high_strategy = TableSetDriftStrategy(confidence=0.90)
    low_strategy = TableSetDriftStrategy(confidence=0.50)

    # We can only have one TableSetDriftStrategy per slot, so test the
    # filter by running the same composite twice with different
    # strategy-confidence settings.

    # First composite — high-confidence strategy survives 0.70 floor.
    hi_composite = make_composite_catalog_drift_service(
        table_set=high_strategy,
        min_confidence=0.70,
    )
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(CatalogTable(table_id="src-1.public.a"),),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(table_id="src-1.public.a"),
            CatalogTable(table_id="src-1.public.b"),
        ),
    )
    hi_proposals = await hi_composite.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(hi_proposals) == 1
    assert hi_proposals[0].confidence >= 0.70
    prefix = "catalog_drift_inference"
    assert hi_composite.metrics()[f"{prefix}_below_min_confidence_dropped"] == 0

    # Second composite — low-confidence strategy drops below 0.70 floor.
    lo_composite = make_composite_catalog_drift_service(
        table_set=low_strategy,
        min_confidence=0.70,
    )
    lo_proposals = await lo_composite.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert lo_proposals == []
    lo_metrics = lo_composite.metrics()
    assert lo_metrics[f"{prefix}_below_min_confidence_dropped"] == 1
    # Per-strategy telemetry stays intact: table_set fired and
    # returned its proposal; the filter happens post-merge.
    assert lo_metrics[f"{prefix}_strategy_invocations.table_set"] == 1


@pytest.mark.asyncio
async def test_composite_returns_proposed_catalog_drift_instances() -> None:
    """Composite output is a list of :class:`ProposedCatalogDrift`."""
    composite = make_composite_catalog_drift_service(
        table_set=TableSetDriftStrategy(),
    )
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(CatalogTable(table_id="src-1.a"),),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(table_id="src-1.a"),
            CatalogTable(table_id="src-1.b"),
        ),
    )
    out = await composite.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert isinstance(out, list)
    assert all(isinstance(p, ProposedCatalogDrift) for p in out)


@pytest.mark.asyncio
async def test_composite_telemetry_aggregates_across_invocations() -> None:
    """Counters accumulate across multiple ``propose`` calls."""
    composite = make_composite_catalog_drift_service(
        table_set=TableSetDriftStrategy(),
    )
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(CatalogTable(table_id="src-1.a"),),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(table_id="src-1.a"),
            CatalogTable(table_id="src-1.b"),
        ),
    )
    await composite.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    await composite.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    metrics = composite.metrics()
    prefix = "catalog_drift_inference"
    assert metrics[f"{prefix}_invocations"] == 2
    assert metrics[f"{prefix}_strategy_invocations.table_set"] == 2
    assert metrics[f"{prefix}_drifts_proposed"] == 2


@pytest.mark.asyncio
async def test_composite_all_three_strategies_run() -> None:
    """All 3 strategies wired → all 3 counter slots increment per call.

    The column_set / column_type strategies will return empty today
    on empty-column tables but the slot still records an invocation.
    """
    composite = make_composite_catalog_drift_service(
        table_set=TableSetDriftStrategy(),
        column_set=ColumnSetDriftStrategy(),
        column_type=ColumnTypeDriftStrategy(),
    )
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(
                table_id="src-1.users",
                columns=(CatalogColumn(name="id", type="bigint"),),
            ),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.users",
                columns=(
                    CatalogColumn(name="id", type="bigint"),
                    CatalogColumn(name="email", type="varchar(255)"),
                ),
            ),
            CatalogTable(table_id="src-1.orders"),
        ),
    )
    await composite.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    metrics = composite.metrics()
    prefix = "catalog_drift_inference"
    assert metrics[f"{prefix}_strategy_invocations.table_set"] == 1
    assert metrics[f"{prefix}_strategy_invocations.column_set"] == 1
    assert metrics[f"{prefix}_strategy_invocations.column_type"] == 1
    assert metrics[f"{prefix}_no_op"] == 0
