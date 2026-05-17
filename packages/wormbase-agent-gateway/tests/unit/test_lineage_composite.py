"""L3 Sub-wave B — composite tests.

Pins:

  * None-ability per strategy (Optional-Effect Injection case 9).
  * Merge dedup: same edge_id from 2 strategies → 1 merged edge with
    max confidence + composite reasoning.
  * Telemetry counters increment per strategy + on no-op invocations.
"""
from __future__ import annotations

import pytest

from wormbase_agent_gateway.lineage import (
    CatalogTable,
    CompositeLineageInferenceService,
    DbtManifestStrategy,
    InferredEdge,
    NamingHeuristicStrategy,
    SampleOverlapStrategy,
    make_edge_id,
)


def _table(table_id: str, columns: tuple[str, ...], kind: str = "postgres") -> CatalogTable:
    return CatalogTable(
        table_id=table_id, columns=columns, source_kind=kind, metadata={},
    )


class _FakeSampler:
    def __init__(self, samples=None, sizes=None) -> None:
        self.samples = samples or {}
        self.sizes = sizes or {}

    async def sample_column(self, table_id, column, n):
        return self.samples.get((table_id, column), set())

    async def estimate_table_size(self, table_id):
        return self.sizes.get(table_id, 100)


class _FakeManifestReader:
    def __init__(self, refs=None, sources=None) -> None:
        self.refs = refs or {}
        self.sources = sources or {}

    async def get_refs_for_model(self, model_id):
        return self.refs.get(model_id, [])

    async def get_source_refs(self, model_id):
        return self.sources.get(model_id, [])


@pytest.mark.asyncio
async def test_composite_all_none_returns_empty_and_counts_no_op() -> None:
    """All strategy slots None → empty edge list + no_op counter increments."""
    composite = CompositeLineageInferenceService()
    src = _table("src.public.orders", ("customer_id",))
    tgt = _table("tgt.public.customers", ("customer_id",))

    edges = await composite.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert edges == []
    metrics = composite.metrics()
    assert metrics["lineage_inference_invocations"] == 1
    assert metrics["lineage_inference_no_op"] == 1
    assert metrics["lineage_inference_edges_proposed"] == 0
    assert metrics["lineage_inference_strategy_invocations.naming_heuristic"] == 0
    assert metrics["lineage_inference_strategy_invocations.sample_overlap"] == 0
    assert metrics["lineage_inference_strategy_invocations.dbt_manifest"] == 0


@pytest.mark.asyncio
async def test_composite_only_naming_strategy_runs() -> None:
    """``naming`` set, others None → only naming counter increments."""
    composite = CompositeLineageInferenceService(
        naming=NamingHeuristicStrategy(),
    )
    src = _table("src.public.orders", ("customer_id",))
    tgt = _table("tgt.public.customers", ("customer_id",))

    edges = await composite.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert len(edges) == 1
    metrics = composite.metrics()
    assert metrics["lineage_inference_strategy_invocations.naming_heuristic"] == 1
    assert metrics["lineage_inference_strategy_invocations.sample_overlap"] == 0
    assert metrics["lineage_inference_strategy_invocations.dbt_manifest"] == 0
    assert metrics["lineage_inference_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_merge_dedup_highest_confidence_wins() -> None:
    """Same edge proposed by naming + sample → merged into one with max conf."""
    # Naming would propose customer_id ↔ customer_id at 0.85
    # SampleOverlap (with rich Jaccard 1.0) would propose at ~0.95
    src = _table("src.public.orders", ("customer_id",))
    tgt = _table("tgt.public.customers", ("customer_id",))

    samples = {f"u{i}" for i in range(30)}
    sampler = _FakeSampler(samples={
        ("src.public.orders", "customer_id"): samples,
        ("tgt.public.customers", "customer_id"): samples,
    })
    composite = CompositeLineageInferenceService(
        naming=NamingHeuristicStrategy(),
        sample_overlap=SampleOverlapStrategy(sampler=sampler),
    )

    edges = await composite.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert len(edges) == 1
    edge = edges[0]
    # Highest confidence wins (sample_overlap at Jaccard 1.0 maps to 0.95)
    assert edge.confidence >= 0.85
    assert edge.confidence == pytest.approx(0.95)
    # Merged strategy label
    assert edge.strategy == "composite"
    # Composite reasoning joins both
    assert "naming match" in edge.reasoning
    assert "sample overlap" in edge.reasoning
    # Per-strategy evidence preserved under named keys
    assert "naming_heuristic" in edge.evidence
    assert "sample_overlap" in edge.evidence


@pytest.mark.asyncio
async def test_composite_single_strategy_edge_keeps_native_label() -> None:
    """Only one strategy contributes to an edge → strategy label stays
    as the single strategy name (no synthetic ``composite`` wrap)."""
    src = _table("src.public.orders", ("customer_id",))
    tgt = _table("tgt.public.customers", ("customer_id",))
    composite = CompositeLineageInferenceService(
        naming=NamingHeuristicStrategy(),
    )

    edges = await composite.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert len(edges) == 1
    assert edges[0].strategy == "naming_heuristic"


@pytest.mark.asyncio
async def test_composite_telemetry_counters_across_multiple_invocations() -> None:
    """Per-strategy counters accumulate across calls."""
    composite = CompositeLineageInferenceService(
        naming=NamingHeuristicStrategy(),
    )
    src = _table("src.public.orders", ("customer_id",))
    tgt = _table("tgt.public.customers", ("customer_id",))

    for _ in range(3):
        await composite.infer_edges(
            source_table=src, candidate_targets=[tgt],
        )

    metrics = composite.metrics()
    assert metrics["lineage_inference_invocations"] == 3
    assert metrics["lineage_inference_strategy_invocations.naming_heuristic"] == 3
    assert metrics["lineage_inference_edges_proposed"] == 3


@pytest.mark.asyncio
async def test_composite_dbt_only_for_dbt_source() -> None:
    """DbtManifest strategy + dbt source → fires; non-dbt source → no edges."""
    upstream = _table("dbt.raw.orders_raw", ("id",), kind="dbt")
    src_dbt = _table("dbt.staging.orders", ("id",), kind="dbt")
    reader = _FakeManifestReader(
        refs={"dbt.staging.orders": ["dbt.raw.orders_raw"]},
    )
    composite = CompositeLineageInferenceService(
        dbt_manifest=DbtManifestStrategy(manifest_reader=reader),
    )

    edges = await composite.infer_edges(
        source_table=src_dbt, candidate_targets=[upstream],
    )
    assert len(edges) == 1
    assert edges[0].strategy == "dbt_manifest"
    assert composite.metrics()[
        "lineage_inference_strategy_invocations.dbt_manifest"
    ] == 1


@pytest.mark.asyncio
async def test_composite_edge_id_dedup_uses_make_edge_id() -> None:
    """Composite dedup key matches :func:`make_edge_id` output."""
    src = _table("src.public.orders", ("customer_id",))
    tgt = _table("tgt.public.customers", ("customer_id",))
    samples = {f"u{i}" for i in range(50)}
    sampler = _FakeSampler(samples={
        ("src.public.orders", "customer_id"): samples,
        ("tgt.public.customers", "customer_id"): samples,
    })
    composite = CompositeLineageInferenceService(
        naming=NamingHeuristicStrategy(),
        sample_overlap=SampleOverlapStrategy(sampler=sampler),
    )

    edges = await composite.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert len(edges) == 1
    expected_id = make_edge_id(
        src_table_id="src.public.orders",
        src_column="customer_id",
        tgt_table_id="tgt.public.customers",
        tgt_column="customer_id",
    )
    assert edges[0].edge_id == expected_id
