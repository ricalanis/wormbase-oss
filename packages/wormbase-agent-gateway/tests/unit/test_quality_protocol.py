"""L7 Sub-wave B — protocol/dataclass tests.

Pins:

  * :func:`make_check_id` determinism / replay stability.
  * Per-tuple distinguishability (column, kind, config affect the hash).
  * Each strategy + the composite implements the
    :class:`QualityCheckProposalService` Protocol (runtime_checkable).
  * Dataclass shape + frozenness.
"""
from __future__ import annotations

from wormbase_agent_gateway.quality import (
    CatalogTable,
    CompositeQualityProposalService,
    DbtTestsStrategy,
    HistoricalStatsStrategy,
    ProposedQualityCheck,
    QualityCheckProposalService,
    SchemaPatternStrategy,
    make_check_id,
)


def test_make_check_id_is_deterministic() -> None:
    """Same inputs → same check_id across calls (replay-stable)."""
    a = make_check_id(
        table_id="src.public.orders",
        check_kind="not_null",
        column="customer_id",
        normalized_config={},
    )
    b = make_check_id(
        table_id="src.public.orders",
        check_kind="not_null",
        column="customer_id",
        normalized_config={},
    )
    assert a == b
    # 32 hex chars (128 bits / 4 bits per hex).
    assert len(a) == 32
    assert all(c in "0123456789abcdef" for c in a)


def test_make_check_id_distinguishes_check_kind() -> None:
    """Same table+column but different kind → different check_id."""
    not_null = make_check_id(
        table_id="src.public.orders",
        check_kind="not_null",
        column="customer_id",
        normalized_config={},
    )
    unique = make_check_id(
        table_id="src.public.orders",
        check_kind="unique",
        column="customer_id",
        normalized_config={},
    )
    assert not_null != unique


def test_make_check_id_distinguishes_column() -> None:
    """Same table+kind but different column → different check_id."""
    a = make_check_id(
        table_id="src.public.orders",
        check_kind="not_null",
        column="customer_id",
        normalized_config={},
    )
    b = make_check_id(
        table_id="src.public.orders",
        check_kind="not_null",
        column="order_id",
        normalized_config={},
    )
    assert a != b


def test_make_check_id_distinguishes_table_grain_vs_column_grain() -> None:
    """``column=None`` (table-level) ≠ ``column='id'`` (column-level)."""
    table_grain = make_check_id(
        table_id="src.public.orders",
        check_kind="freshness",
        column=None,
        normalized_config={"max_age_hours": 24},
    )
    col_grain = make_check_id(
        table_id="src.public.orders",
        check_kind="freshness",
        column="updated_at",
        normalized_config={"max_age_hours": 24},
    )
    assert table_grain != col_grain


def test_make_check_id_distinguishes_config() -> None:
    """Same table+kind+column but different config → different check_id."""
    a = make_check_id(
        table_id="src.public.orders",
        check_kind="freshness",
        column="updated_at",
        normalized_config={"max_age_hours": 24},
    )
    b = make_check_id(
        table_id="src.public.orders",
        check_kind="freshness",
        column="updated_at",
        normalized_config={"max_age_hours": 168},
    )
    assert a != b


def test_make_check_id_normalizes_config_key_order() -> None:
    """``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}`` → same check_id."""
    a = make_check_id(
        table_id="src.public.orders",
        check_kind="value_range",
        column="amount",
        normalized_config={"min": 0, "max": 1000},
    )
    b = make_check_id(
        table_id="src.public.orders",
        check_kind="value_range",
        column="amount",
        normalized_config={"max": 1000, "min": 0},
    )
    assert a == b


def test_strategies_satisfy_quality_check_proposal_service_protocol() -> None:
    """All three strategies + the composite are instances of
    :class:`QualityCheckProposalService` per ``runtime_checkable``."""

    class _FakeDbtTestReader:
        async def get_tests_for_model(self, model_id):
            return []

    class _FakeHistoricalStatsReader:
        async def get_snapshots_for_table(self, table_id):
            return []

    schema = SchemaPatternStrategy()
    dbt = DbtTestsStrategy(manifest_reader=_FakeDbtTestReader())
    hist = HistoricalStatsStrategy(reader=_FakeHistoricalStatsReader())
    composite = CompositeQualityProposalService()

    for service in (schema, dbt, hist, composite):
        assert isinstance(service, QualityCheckProposalService), (
            f"{type(service).__name__} does not satisfy "
            f"QualityCheckProposalService"
        )
        assert hasattr(service, "name")
        assert isinstance(service.name, str)


def test_proposed_quality_check_is_frozen() -> None:
    """``ProposedQualityCheck`` is a frozen dataclass."""
    check = ProposedQualityCheck(
        check_id="abc",
        table_id="src.public.orders",
        column="customer_id",
        check_kind="not_null",
        config={},
        confidence=0.85,
        strategy="schema_pattern",
        reasoning="test",
        evidence={"observed_null_ratio": 0.01},
    )
    # Frozen dataclass — mutation raises FrozenInstanceError (subclass of
    # AttributeError in older Python; current 3.13+ raises AttributeError).
    try:
        check.check_id = "modified"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("ProposedQualityCheck should be frozen")


def test_catalog_table_reused_from_lineage_module() -> None:
    """``CatalogTable`` is the same class as the lineage module's.

    The quality subpackage re-exports the lineage CatalogTable so the
    two L-axis Compounding services share the per-table input shape.
    """
    from wormbase_agent_gateway.lineage import (
        CatalogTable as LineageCatalogTable,
    )

    assert CatalogTable is LineageCatalogTable

    ct = CatalogTable(
        table_id="src.public.orders",
        columns=("id", "customer_id"),
        source_kind="postgres",
        metadata={},
    )
    assert ct.table_id == "src.public.orders"
    assert ct.columns == ("id", "customer_id")


def test_strategy_names_match_spec() -> None:
    """Strategy ``name`` attributes match the spec's canonical identifiers."""
    assert SchemaPatternStrategy.name == "schema_pattern"
    assert DbtTestsStrategy.name == "dbt_tests"
    assert HistoricalStatsStrategy.name == "historical_stats"
    assert CompositeQualityProposalService.name == "composite"
