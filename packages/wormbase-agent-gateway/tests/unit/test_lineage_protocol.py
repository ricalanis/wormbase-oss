"""L3 Sub-wave B — protocol/dataclass tests.

Pins:

  * :func:`make_edge_id` determinism / replay stability.
  * :class:`InferredEdge.edge_id` matches :func:`make_edge_id` for the
    same endpoint tuple.
  * Each strategy + the composite implements the
    :class:`LineageInferenceService` Protocol (runtime_checkable).
"""
from __future__ import annotations

from wormbase_agent_gateway.lineage import (
    CatalogTable,
    CompositeLineageInferenceService,
    DbtManifestStrategy,
    InferredEdge,
    LineageInferenceConfig,
    LineageInferenceService,
    NamingHeuristicStrategy,
    SampleOverlapStrategy,
    make_edge_id,
)


def test_make_edge_id_is_deterministic() -> None:
    """Same inputs → same edge_id across calls."""
    a = make_edge_id(
        src_table_id="src.public.orders",
        src_column="customer_id",
        tgt_table_id="tgt.public.customers",
        tgt_column="id",
    )
    b = make_edge_id(
        src_table_id="src.public.orders",
        src_column="customer_id",
        tgt_table_id="tgt.public.customers",
        tgt_column="id",
    )
    assert a == b
    # 32 hex chars (128 bits / 4 bits per hex).
    assert len(a) == 32
    assert all(c in "0123456789abcdef" for c in a)


def test_make_edge_id_distinguishes_direction() -> None:
    """``(src, tgt)`` ≠ ``(tgt, src)`` — direction-aware identity."""
    forward = make_edge_id(
        src_table_id="A.s.t",
        src_column="c",
        tgt_table_id="B.s.t",
        tgt_column="c",
    )
    reverse = make_edge_id(
        src_table_id="B.s.t",
        src_column="c",
        tgt_table_id="A.s.t",
        tgt_column="c",
    )
    assert forward != reverse


def test_make_edge_id_distinguishes_whole_table_vs_column_grain() -> None:
    """Whole-table edges (None column) ≠ column-grain edges."""
    whole = make_edge_id(
        src_table_id="A.s.t", src_column=None,
        tgt_table_id="B.s.t", tgt_column=None,
    )
    col_grain = make_edge_id(
        src_table_id="A.s.t", src_column="id",
        tgt_table_id="B.s.t", tgt_column="id",
    )
    assert whole != col_grain


def test_inferred_edge_id_property_matches_make_edge_id() -> None:
    """``InferredEdge.edge_id`` and :func:`make_edge_id` agree."""
    edge = InferredEdge(
        src_table_id="src.public.orders",
        src_column="customer_id",
        tgt_table_id="tgt.public.customers",
        tgt_column="id",
        confidence=0.85,
        strategy="naming_heuristic",
        reasoning="exact match",
        evidence={"match_kind": "exact"},
    )
    expected = make_edge_id(
        src_table_id="src.public.orders",
        src_column="customer_id",
        tgt_table_id="tgt.public.customers",
        tgt_column="id",
    )
    assert edge.edge_id == expected


def test_strategies_satisfy_lineage_inference_service_protocol() -> None:
    """All three concrete strategies + the composite are instances of
    :class:`LineageInferenceService` per ``runtime_checkable``."""

    class _FakeSampler:
        async def sample_column(self, table_id, column, n):
            return set()

        async def estimate_table_size(self, table_id):
            return 0

    class _FakeManifestReader:
        async def get_refs_for_model(self, model_id):
            return []

        async def get_source_refs(self, model_id):
            return []

    naming = NamingHeuristicStrategy()
    sample = SampleOverlapStrategy(sampler=_FakeSampler())
    dbt = DbtManifestStrategy(manifest_reader=_FakeManifestReader())
    composite = CompositeLineageInferenceService()

    for service in (naming, sample, dbt, composite):
        assert isinstance(service, LineageInferenceService), (
            f"{type(service).__name__} does not satisfy LineageInferenceService"
        )
        assert hasattr(service, "name")
        assert isinstance(service.name, str)


def test_catalog_table_immutable_columns_tuple() -> None:
    """``CatalogTable`` is frozen + ``columns`` is a tuple (hashable)."""
    ct = CatalogTable(
        table_id="src.public.orders",
        columns=("id", "customer_id", "amount"),
        source_kind="postgres",
        metadata={"row_count": 1234},
    )
    assert ct.table_id == "src.public.orders"
    assert ct.columns == ("id", "customer_id", "amount")
    assert ct.source_kind == "postgres"


def test_lineage_inference_config_defaults() -> None:
    """``LineageInferenceConfig`` defaults match the Sub-wave B contract."""
    config = LineageInferenceConfig()
    assert config.edit_distance_max == 2
    assert config.min_shared_prefix == 3
    assert config.jaccard_threshold == 0.5
    assert config.value_richness_min == 10
    assert config.max_table_size == 10_000_000
    assert config.sample_size == 1000
