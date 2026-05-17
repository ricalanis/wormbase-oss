"""L7 Sub-wave B — strategy tests.

Per-strategy behaviour pinned independently:

  * :class:`SchemaPatternStrategy` — naming-based + metadata-based
    heuristics for each of the 4 check kinds it emits.
  * :class:`DbtTestsStrategy` — only fires for ``source_kind="dbt"``,
    maps the 5 supported dbt-test names to QualityCheckKinds.
  * :class:`HistoricalStatsStrategy` — requires N≥3 snapshots; emits
    row_count_range / freshness / enum_membership on stable signals.
"""
from __future__ import annotations

import pytest

from wormbase_agent_gateway.quality import (
    CatalogTable,
    DbtTestsStrategy,
    HistoricalStatsStrategy,
    SchemaPatternStrategy,
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


# ---------------------------------------------------------------------------
# SchemaPatternStrategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_pattern_not_null_violation_proposes_check() -> None:
    """NOT NULL column with observed nulls → not_null check at 0.85."""
    strategy = SchemaPatternStrategy()
    table = _table(
        "src.public.orders",
        ("customer_id",),
        metadata={
            "columns": [
                {
                    "name": "customer_id",
                    "type": "varchar",
                    "nullable": False,
                    "observed_null_ratio": 0.02,
                },
            ],
        },
    )
    proposals = await strategy.propose_checks(table=table)
    nn = [p for p in proposals if p.check_kind == "not_null"]
    assert len(nn) == 1
    assert nn[0].confidence == 0.85
    assert nn[0].column == "customer_id"
    assert nn[0].evidence["match_kind"] == "not_null_violation"
    assert nn[0].evidence["observed_null_ratio"] == 0.02


@pytest.mark.asyncio
async def test_schema_pattern_not_null_clean_column_no_check() -> None:
    """NOT NULL + zero nulls observed → no not_null check (already enforced)."""
    strategy = SchemaPatternStrategy()
    table = _table(
        "src.public.orders",
        ("customer_id",),
        metadata={
            "columns": [
                {
                    "name": "customer_id",
                    "type": "varchar",
                    "nullable": False,
                    "observed_null_ratio": 0.0,
                },
            ],
        },
    )
    proposals = await strategy.propose_checks(table=table)
    nn = [p for p in proposals if p.check_kind == "not_null"]
    assert nn == []


@pytest.mark.asyncio
async def test_schema_pattern_id_named_column_proposes_unique() -> None:
    """``id`` and ``*_id`` columns → unique check at 0.80."""
    strategy = SchemaPatternStrategy()
    table = _table("src.public.orders", ("id", "customer_id", "amount"))
    proposals = await strategy.propose_checks(table=table)
    uniques = [p for p in proposals if p.check_kind == "unique"]
    cols = {p.column for p in uniques}
    assert "id" in cols
    assert "customer_id" in cols
    assert "amount" not in cols
    for p in uniques:
        assert p.confidence == 0.80


@pytest.mark.asyncio
async def test_schema_pattern_timestamp_named_column_proposes_freshness() -> None:
    """``*_at``/``*_ts``/``*_time`` columns → freshness check at 0.70."""
    strategy = SchemaPatternStrategy(freshness_default_hours=48)
    table = _table(
        "src.public.orders",
        ("created_at", "updated_ts", "deleted_time", "amount"),
    )
    proposals = await strategy.propose_checks(table=table)
    fresh = [p for p in proposals if p.check_kind == "freshness"]
    cols = {p.column for p in fresh}
    assert {"created_at", "updated_ts", "deleted_time"}.issubset(cols)
    assert "amount" not in cols
    for p in fresh:
        assert p.confidence == 0.70
        assert p.config == {"max_age_hours": 48}


@pytest.mark.asyncio
async def test_schema_pattern_timestamp_typed_column_proposes_freshness() -> None:
    """Type-based timestamp detection also fires."""
    strategy = SchemaPatternStrategy()
    table = _table(
        "src.public.events",
        ("event_when",),
        metadata={
            "columns": [
                {"name": "event_when", "type": "timestamptz"},
            ],
        },
    )
    proposals = await strategy.propose_checks(table=table)
    fresh = [p for p in proposals if p.check_kind == "freshness"]
    assert len(fresh) == 1
    assert fresh[0].column == "event_when"


@pytest.mark.asyncio
async def test_schema_pattern_low_cardinality_proposes_enum() -> None:
    """Low distinct_count → enum_membership at 0.65."""
    strategy = SchemaPatternStrategy(low_cardinality_max=10)
    table = _table(
        "src.public.orders",
        ("region",),
        metadata={
            "columns": [
                {"name": "region", "type": "varchar", "distinct_count": 5},
            ],
        },
    )
    proposals = await strategy.propose_checks(table=table)
    enums = [p for p in proposals if p.check_kind == "enum_membership"]
    assert len(enums) == 1
    assert enums[0].confidence == 0.65
    assert enums[0].column == "region"


@pytest.mark.asyncio
async def test_schema_pattern_high_cardinality_no_enum() -> None:
    """High distinct_count → no enum_membership."""
    strategy = SchemaPatternStrategy(low_cardinality_max=10)
    table = _table(
        "src.public.orders",
        ("user_email",),
        metadata={
            "columns": [
                {
                    "name": "user_email",
                    "type": "varchar",
                    "distinct_count": 50000,
                },
            ],
        },
    )
    proposals = await strategy.propose_checks(table=table)
    enums = [p for p in proposals if p.check_kind == "enum_membership"]
    assert enums == []


@pytest.mark.asyncio
async def test_schema_pattern_stop_list_filters_trivial_names() -> None:
    """``name``, ``description`` etc. → no proposals (stop list)."""
    strategy = SchemaPatternStrategy()
    table = _table("src.public.docs", ("name", "description"))
    proposals = await strategy.propose_checks(table=table)
    assert proposals == []


@pytest.mark.asyncio
async def test_schema_pattern_check_id_is_deterministic() -> None:
    """Same table → same check_ids across calls (replay-stable)."""
    strategy = SchemaPatternStrategy()
    table = _table("src.public.orders", ("customer_id", "created_at"))
    proposals_a = await strategy.propose_checks(table=table)
    proposals_b = await strategy.propose_checks(table=table)
    ids_a = sorted(p.check_id for p in proposals_a)
    ids_b = sorted(p.check_id for p in proposals_b)
    assert ids_a == ids_b


@pytest.mark.asyncio
async def test_schema_pattern_no_metadata_still_emits_naming_heuristics() -> None:
    """Catalog mirror today emits no per-column stats; naming heuristics
    must still fire so the strategy is productive today."""
    strategy = SchemaPatternStrategy()
    table = _table("src.public.orders", ("id", "user_id", "created_at"))
    proposals = await strategy.propose_checks(table=table)
    # 2 unique + 1 freshness (no not_null/enum without stats)
    kinds = {p.check_kind for p in proposals}
    assert "unique" in kinds
    assert "freshness" in kinds


# ---------------------------------------------------------------------------
# DbtTestsStrategy
# ---------------------------------------------------------------------------


class _FakeDbtTestReader:
    def __init__(
        self, tests: dict[str, list[dict]] | None = None,
    ) -> None:
        self.tests = tests or {}
        self.calls: list[str] = []

    async def get_tests_for_model(self, model_id: str) -> list[dict]:
        self.calls.append(model_id)
        return self.tests.get(model_id, [])


@pytest.mark.asyncio
async def test_dbt_tests_strategy_only_fires_for_dbt_source_kind() -> None:
    """Non-dbt source kinds → no proposals (manifest strategy is dbt-only)."""
    reader = _FakeDbtTestReader(
        tests={"any": [{"test_name": "not_null", "column": "id"}]},
    )
    strategy = DbtTestsStrategy(manifest_reader=reader)
    pg_table = _table("src.public.orders", ("id",), kind="postgres")
    proposals = await strategy.propose_checks(table=pg_table)
    assert proposals == []
    # Optimisation: reader is NOT called for non-dbt sources.
    assert reader.calls == []


@pytest.mark.asyncio
async def test_dbt_tests_strategy_maps_not_null_at_high_confidence() -> None:
    """``not_null`` dbt test → ``not_null`` check at 0.99."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "not_null", "column": "customer_id"},
            ],
        },
    )
    strategy = DbtTestsStrategy(manifest_reader=reader)
    table = _table("dbt.staging.orders", ("customer_id",), kind="dbt")
    proposals = await strategy.propose_checks(table=table)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.check_kind == "not_null"
    assert p.confidence == 0.99
    assert p.column == "customer_id"


@pytest.mark.asyncio
async def test_dbt_tests_strategy_maps_unique() -> None:
    """``unique`` dbt test → ``unique`` check at 0.99."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "unique", "column": "id"},
            ],
        },
    )
    strategy = DbtTestsStrategy(manifest_reader=reader)
    table = _table("dbt.staging.orders", ("id",), kind="dbt")
    proposals = await strategy.propose_checks(table=table)
    assert len(proposals) == 1
    assert proposals[0].check_kind == "unique"
    assert proposals[0].confidence == 0.99


@pytest.mark.asyncio
async def test_dbt_tests_strategy_maps_accepted_values_to_enum() -> None:
    """``accepted_values`` → ``enum_membership`` with values in config."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {
                    "test_name": "accepted_values",
                    "column": "status",
                    "config": {"values": ["pending", "fulfilled", "refunded"]},
                },
            ],
        },
    )
    strategy = DbtTestsStrategy(manifest_reader=reader)
    table = _table("dbt.staging.orders", ("status",), kind="dbt")
    proposals = await strategy.propose_checks(table=table)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.check_kind == "enum_membership"
    assert p.config == {
        "allowed_values": ["pending", "fulfilled", "refunded"],
    }
    assert p.confidence == 0.99


@pytest.mark.asyncio
async def test_dbt_tests_strategy_maps_row_count() -> None:
    """``dbt_utils.row_count`` → ``row_count_range`` at 0.95."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {
                    "test_name": "dbt_utils.row_count",
                    "column": None,
                    "config": {"min_value": 100, "max_value": 10000},
                },
            ],
        },
    )
    strategy = DbtTestsStrategy(manifest_reader=reader)
    table = _table("dbt.staging.orders", ("id",), kind="dbt")
    proposals = await strategy.propose_checks(table=table)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.check_kind == "row_count_range"
    assert p.config == {"min_rows": 100, "max_rows": 10000}
    assert p.column is None  # table-grain
    assert p.confidence == 0.95


@pytest.mark.asyncio
async def test_dbt_tests_strategy_maps_test_freshness() -> None:
    """``dbt_utils.test_freshness`` → ``freshness`` at 0.95."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {
                    "test_name": "dbt_utils.test_freshness",
                    "column": "updated_at",
                    "config": {"max_age_hours": 12},
                },
            ],
        },
    )
    strategy = DbtTestsStrategy(manifest_reader=reader)
    table = _table("dbt.staging.orders", ("updated_at",), kind="dbt")
    proposals = await strategy.propose_checks(table=table)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.check_kind == "freshness"
    assert p.config == {"max_age_hours": 12}
    assert p.confidence == 0.95


@pytest.mark.asyncio
async def test_dbt_tests_strategy_skips_unknown_test_names() -> None:
    """A dbt test name not in the map → silently skipped."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "some_custom_test", "column": "id"},
                {"test_name": "not_null", "column": "customer_id"},
            ],
        },
    )
    strategy = DbtTestsStrategy(manifest_reader=reader)
    table = _table(
        "dbt.staging.orders", ("id", "customer_id"), kind="dbt",
    )
    proposals = await strategy.propose_checks(table=table)
    # Only the not_null mapping fires.
    assert len(proposals) == 1
    assert proposals[0].check_kind == "not_null"


@pytest.mark.asyncio
async def test_dbt_tests_strategy_evidence_carries_test_name() -> None:
    """Evidence includes the original dbt test name for traceability."""
    reader = _FakeDbtTestReader(
        tests={
            "dbt.staging.orders": [
                {"test_name": "not_null", "column": "customer_id"},
            ],
        },
    )
    strategy = DbtTestsStrategy(manifest_reader=reader)
    table = _table("dbt.staging.orders", ("customer_id",), kind="dbt")
    proposals = await strategy.propose_checks(table=table)
    assert proposals[0].evidence["dbt_test_name"] == "not_null"


# ---------------------------------------------------------------------------
# HistoricalStatsStrategy
# ---------------------------------------------------------------------------


class _FakeHistoricalReader:
    def __init__(
        self, snapshots: dict[str, list[dict]] | None = None,
    ) -> None:
        self.snapshots = snapshots or {}

    async def get_snapshots_for_table(self, table_id: str) -> list[dict]:
        return self.snapshots.get(table_id, [])


@pytest.mark.asyncio
async def test_historical_stats_returns_empty_when_no_snapshots() -> None:
    """No snapshots → no proposals (honest-stub posture)."""
    reader = _FakeHistoricalReader()
    strategy = HistoricalStatsStrategy(reader=reader)
    table = _table("src.public.orders", ("id",))
    proposals = await strategy.propose_checks(table=table)
    assert proposals == []


@pytest.mark.asyncio
async def test_historical_stats_requires_minimum_snapshots() -> None:
    """Fewer than ``min_snapshots`` → no proposals."""
    reader = _FakeHistoricalReader(
        snapshots={
            "src.public.orders": [
                {"row_count": 1000},
                {"row_count": 1100},
            ],
        },
    )
    strategy = HistoricalStatsStrategy(reader=reader, min_snapshots=3)
    table = _table("src.public.orders", ("id",))
    proposals = await strategy.propose_checks(table=table)
    assert proposals == []


@pytest.mark.asyncio
async def test_historical_stats_proposes_row_count_range() -> None:
    """≥3 snapshots with row_counts → row_count_range proposal at 0.75."""
    reader = _FakeHistoricalReader(
        snapshots={
            "src.public.orders": [
                {"row_count": 1000},
                {"row_count": 1100},
                {"row_count": 1050},
            ],
        },
    )
    strategy = HistoricalStatsStrategy(
        reader=reader, min_snapshots=3, row_count_buffer_ratio=0.2,
    )
    table = _table("src.public.orders", ("id",))
    proposals = await strategy.propose_checks(table=table)
    rc = [p for p in proposals if p.check_kind == "row_count_range"]
    assert len(rc) == 1
    p = rc[0]
    assert p.confidence == 0.75
    assert p.column is None  # table-grain
    # min_rows ≤ observed min × (1 - 0.2) and max_rows ≥ observed max × 1.2
    assert p.config["min_rows"] <= 800
    assert p.config["max_rows"] >= 1320


@pytest.mark.asyncio
async def test_historical_stats_proposes_freshness() -> None:
    """≥3 snapshots with latest-timestamp ages → freshness proposal."""
    reader = _FakeHistoricalReader(
        snapshots={
            "src.public.orders": [
                {"latest_timestamp_age_hours": 1.0},
                {"latest_timestamp_age_hours": 2.0},
                {"latest_timestamp_age_hours": 3.0},
            ],
        },
    )
    strategy = HistoricalStatsStrategy(
        reader=reader, min_snapshots=3, freshness_buffer_ratio=1.5,
    )
    table = _table("src.public.orders", ("id",))
    proposals = await strategy.propose_checks(table=table)
    fresh = [p for p in proposals if p.check_kind == "freshness"]
    assert len(fresh) == 1
    p = fresh[0]
    assert p.confidence == 0.75
    # max age 3h × 1.5 buffer = 4.5 → int truncates to 4
    assert p.config["max_age_hours"] >= 4


@pytest.mark.asyncio
async def test_historical_stats_proposes_enum_for_stable_value_set() -> None:
    """Stable distinct-value set across snapshots → enum_membership."""
    reader = _FakeHistoricalReader(
        snapshots={
            "src.public.orders": [
                {
                    "columns": [
                        {
                            "name": "status",
                            "distinct_values": ["pending", "fulfilled"],
                        },
                    ],
                },
                {
                    "columns": [
                        {
                            "name": "status",
                            "distinct_values": ["pending", "fulfilled"],
                        },
                    ],
                },
                {
                    "columns": [
                        {
                            "name": "status",
                            "distinct_values": ["fulfilled", "pending"],
                        },
                    ],
                },
            ],
        },
    )
    strategy = HistoricalStatsStrategy(reader=reader, min_snapshots=3)
    table = _table("src.public.orders", ("status",))
    proposals = await strategy.propose_checks(table=table)
    enums = [p for p in proposals if p.check_kind == "enum_membership"]
    assert len(enums) == 1
    p = enums[0]
    assert p.column == "status"
    assert p.confidence == 0.80
    assert p.config == {"allowed_values": ["fulfilled", "pending"]}


@pytest.mark.asyncio
async def test_historical_stats_no_enum_on_unstable_value_set() -> None:
    """Snapshot distinct-sets that drift → no enum_membership."""
    reader = _FakeHistoricalReader(
        snapshots={
            "src.public.orders": [
                {"columns": [{"name": "status", "distinct_values": ["a", "b"]}]},
                {"columns": [{"name": "status", "distinct_values": ["a", "b", "c"]}]},
                {"columns": [{"name": "status", "distinct_values": ["a", "d"]}]},
            ],
        },
    )
    strategy = HistoricalStatsStrategy(reader=reader, min_snapshots=3)
    table = _table("src.public.orders", ("status",))
    proposals = await strategy.propose_checks(table=table)
    enums = [p for p in proposals if p.check_kind == "enum_membership"]
    assert enums == []


@pytest.mark.asyncio
async def test_historical_stats_check_id_is_deterministic() -> None:
    """Same snapshots → same check_ids (replay-stable)."""
    snapshots = [
        {"row_count": 1000},
        {"row_count": 1100},
        {"row_count": 1050},
    ]
    reader = _FakeHistoricalReader(
        snapshots={"src.public.orders": snapshots},
    )
    strategy = HistoricalStatsStrategy(reader=reader, min_snapshots=3)
    table = _table("src.public.orders", ("id",))
    a = await strategy.propose_checks(table=table)
    b = await strategy.propose_checks(table=table)
    assert sorted(p.check_id for p in a) == sorted(p.check_id for p in b)
