"""L7 Sub-wave B — composite tests.

Pins:

  * None-ability per strategy (Optional-Effect Injection case 10).
  * Merge dedup: same check_id from 2 strategies → 1 merged proposal
    with max confidence + composite reasoning.
  * Telemetry counters increment per strategy + on no-op invocations.
"""
from __future__ import annotations

import pytest

from wormbase_agent_gateway.quality import (
    CatalogTable,
    CompositeQualityProposalService,
    DbtTestsStrategy,
    HistoricalStatsStrategy,
    SchemaPatternStrategy,
    make_check_id,
)


def _table(
    table_id: str,
    columns: tuple[str, ...],
    kind: str = "postgres",
    metadata: dict | None = None,
) -> CatalogTable:
    return CatalogTable(
        table_id=table_id,
        columns=columns,
        source_kind=kind,
        metadata=metadata or {},
    )


class _FakeDbtTestReader:
    def __init__(self, tests=None) -> None:
        self.tests = tests or {}

    async def get_tests_for_model(self, model_id):
        return self.tests.get(model_id, [])


class _FakeHistoricalReader:
    def __init__(self, snapshots=None) -> None:
        self.snapshots = snapshots or {}

    async def get_snapshots_for_table(self, table_id):
        return self.snapshots.get(table_id, [])


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_all_none_returns_empty_and_counts_no_op() -> None:
    """All strategy slots None → empty proposal list + no_op counter."""
    composite = CompositeQualityProposalService()
    table = _table("src.public.orders", ("id",))
    proposals = await composite.propose_checks(table=table)
    assert proposals == []
    metrics = composite.metrics()
    assert metrics["quality_inference_invocations"] == 1
    assert metrics["quality_inference_no_op"] == 1
    assert metrics["quality_inference_checks_proposed"] == 0
    assert metrics["quality_inference_strategy_invocations.schema_pattern"] == 0
    assert metrics["quality_inference_strategy_invocations.dbt_tests"] == 0
    assert metrics["quality_inference_strategy_invocations.historical_stats"] == 0


@pytest.mark.asyncio
async def test_composite_only_schema_pattern_runs() -> None:
    """``schema_pattern`` set, others None → only that counter increments."""
    composite = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )
    table = _table("src.public.orders", ("customer_id",))
    proposals = await composite.propose_checks(table=table)
    # Naming-based unique check fires
    assert len(proposals) >= 1
    metrics = composite.metrics()
    assert metrics["quality_inference_strategy_invocations.schema_pattern"] == 1
    assert metrics["quality_inference_strategy_invocations.dbt_tests"] == 0
    assert metrics["quality_inference_strategy_invocations.historical_stats"] == 0
    assert metrics["quality_inference_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_only_dbt_tests_runs() -> None:
    """``dbt_tests`` set, others None → only that counter increments."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "not_null", "column": "customer_id"},
            ],
        },
    )
    composite = CompositeQualityProposalService(
        dbt_tests=DbtTestsStrategy(manifest_reader=reader),
    )
    table = _table("dbt.staging.orders", ("customer_id",), kind="dbt")
    proposals = await composite.propose_checks(table=table)
    assert len(proposals) == 1
    metrics = composite.metrics()
    assert metrics["quality_inference_strategy_invocations.dbt_tests"] == 1
    assert metrics["quality_inference_strategy_invocations.schema_pattern"] == 0


@pytest.mark.asyncio
async def test_composite_only_historical_stats_runs() -> None:
    """``historical_stats`` set, others None → only that counter increments."""
    reader = _FakeHistoricalReader(
        snapshots={
            "src.public.orders": [
                {"row_count": 1000},
                {"row_count": 1100},
                {"row_count": 1050},
            ],
        },
    )
    composite = CompositeQualityProposalService(
        historical_stats=HistoricalStatsStrategy(reader=reader, min_snapshots=3),
    )
    table = _table("src.public.orders", ("id",))
    proposals = await composite.propose_checks(table=table)
    assert any(p.check_kind == "row_count_range" for p in proposals)
    metrics = composite.metrics()
    assert metrics["quality_inference_strategy_invocations.historical_stats"] == 1


# ---------------------------------------------------------------------------
# Merge + dedup contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_merge_dedup_highest_confidence_wins() -> None:
    """Same check proposed by schema_pattern + dbt_tests → merged into
    one with the max confidence."""
    # schema_pattern would propose a unique check on ``customer_id`` at 0.80.
    # dbt_tests would propose a unique check on ``customer_id`` at 0.99.
    # Both produce the same check_id (same table, kind, column, config={}).
    table = _table(
        "dbt.staging.orders", ("customer_id",), kind="dbt",
    )
    dbt_reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "unique", "column": "customer_id"},
            ],
        },
    )
    composite = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
        dbt_tests=DbtTestsStrategy(manifest_reader=dbt_reader),
    )
    proposals = await composite.propose_checks(table=table)
    uniques = [p for p in proposals if p.check_kind == "unique"]
    assert len(uniques) == 1
    p = uniques[0]
    # Highest-confidence wins
    assert p.confidence == 0.99
    # Composite label
    assert p.strategy == "composite"
    # Both reasonings present
    assert "id-naming pattern" in p.reasoning
    assert "dbt test" in p.reasoning
    # Per-strategy evidence preserved under named keys
    assert "schema_pattern" in p.evidence
    assert "dbt_tests" in p.evidence


@pytest.mark.asyncio
async def test_composite_single_strategy_proposal_keeps_native_label() -> None:
    """Only one strategy contributes → strategy label stays unwrapped."""
    composite = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )
    table = _table("src.public.orders", ("customer_id",))
    proposals = await composite.propose_checks(table=table)
    uniques = [p for p in proposals if p.check_kind == "unique"]
    assert len(uniques) == 1
    assert uniques[0].strategy == "schema_pattern"


@pytest.mark.asyncio
async def test_composite_check_id_dedup_uses_make_check_id() -> None:
    """Composite dedup key matches :func:`make_check_id` output."""
    table = _table(
        "dbt.staging.orders", ("customer_id",), kind="dbt",
    )
    dbt_reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "unique", "column": "customer_id"},
            ],
        },
    )
    composite = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
        dbt_tests=DbtTestsStrategy(manifest_reader=dbt_reader),
    )
    proposals = await composite.propose_checks(table=table)
    uniques = [p for p in proposals if p.check_kind == "unique"]
    expected_id = make_check_id(
        table_id="dbt.staging.orders",
        check_kind="unique",
        column="customer_id",
        normalized_config={},
    )
    assert uniques[0].check_id == expected_id


@pytest.mark.asyncio
async def test_composite_telemetry_counters_accumulate_across_invocations() -> None:
    """Per-strategy counters accumulate across calls."""
    composite = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )
    table = _table("src.public.orders", ("customer_id",))
    for _ in range(3):
        await composite.propose_checks(table=table)
    metrics = composite.metrics()
    assert metrics["quality_inference_invocations"] == 3
    assert metrics["quality_inference_strategy_invocations.schema_pattern"] == 3
    # 1 unique check per invocation × 3 invocations = 3 cumulative checks
    assert metrics["quality_inference_checks_proposed"] == 3


@pytest.mark.asyncio
async def test_composite_dbt_only_for_dbt_source_no_proposal_for_other_kinds() -> None:
    """DbtTests + non-dbt source → no proposals from dbt; schema still fires."""
    dbt_reader = _FakeDbtTestReader(
        tests={"_unused": [{"test_name": "not_null", "column": "id"}]},
    )
    composite = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
        dbt_tests=DbtTestsStrategy(manifest_reader=dbt_reader),
    )
    pg_table = _table("src.public.orders", ("customer_id",), kind="postgres")
    proposals = await composite.propose_checks(table=pg_table)
    # schema_pattern fires (naming heuristic on customer_id), dbt_tests doesn't
    assert any(p.strategy == "schema_pattern" for p in proposals)
    assert not any(
        p.strategy == "dbt_tests" or "dbt_tests" in p.evidence
        for p in proposals
    )


@pytest.mark.asyncio
async def test_composite_no_proposals_returns_empty_without_no_op_increment() -> None:
    """Strategies wired but each returns [] (e.g. empty table) → empty
    proposals, but ``no_op`` counter does NOT fire (no_op is reserved for
    the "all strategies None" path per the doctrine)."""
    composite = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )
    # Empty columns + no metadata → no proposals.
    table = _table("src.public.empty", ())
    proposals = await composite.propose_checks(table=table)
    assert proposals == []
    metrics = composite.metrics()
    # Strategy ran (counter = 1) but produced nothing — not a no-op.
    assert metrics["quality_inference_strategy_invocations.schema_pattern"] == 1
    assert metrics["quality_inference_no_op"] == 0
    assert metrics["quality_inference_checks_proposed"] == 0


@pytest.mark.asyncio
async def test_composite_all_three_strategies_wired() -> None:
    """All 3 strategies wired → all 3 counters fire on a single invocation."""
    dbt_reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "not_null", "column": "customer_id"},
            ],
        },
    )
    hist_reader = _FakeHistoricalReader(
        snapshots={
            "dbt.staging.orders": [
                {"row_count": 1000},
                {"row_count": 1100},
                {"row_count": 1050},
            ],
        },
    )
    composite = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
        dbt_tests=DbtTestsStrategy(manifest_reader=dbt_reader),
        historical_stats=HistoricalStatsStrategy(
            reader=hist_reader, min_snapshots=3,
        ),
    )
    table = _table("dbt.staging.orders", ("customer_id",), kind="dbt")
    await composite.propose_checks(table=table)
    metrics = composite.metrics()
    assert metrics["quality_inference_strategy_invocations.schema_pattern"] == 1
    assert metrics["quality_inference_strategy_invocations.dbt_tests"] == 1
    assert metrics["quality_inference_strategy_invocations.historical_stats"] == 1
    assert metrics["quality_inference_no_op"] == 0
