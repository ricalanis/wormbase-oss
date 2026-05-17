"""L4 Sub-wave B — Compounding-factory integration tests.

Pins the L4 schema-evolution-impact axis end-to-end through a real
``ReactivityRegistry`` + ``ReactivityRunner`` + ``InMemoryLedger``:

  * Fires on ``external_catalog_imported`` events that carry a
    ``column_changes`` list.
  * No-op when ``impact_service`` is None (Optional-Effect Injection
    case 11, absent path).
  * No-op when ``catalog_reader`` is None.
  * Quality filter: missing ``source_id`` → no fire.
  * Idempotency filter: re-proposing within window suppressed.
  * Multi-column delta → one PEVR cycle per change.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_agent_gateway.reactivities import (
    make_schema_impact_discovery_reactivity,
)
from wormbase_agent_gateway.schema_impact import (
    CompositeSchemaImpactService,
    LineageEdgeImpactStrategy,
    LineageEdgeRecord,
    TypeCoercionImpactStrategy,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a004f")


class _FakeReader:
    """Test double for :class:`LineageEdgeReader`."""

    def __init__(self, edges: list[LineageEdgeRecord] | None = None) -> None:
        self.edges = edges or []
        self.calls: list[tuple[str, str]] = []

    async def list_confirmed_edges_for_source_column(
        self, *, source_id: str, src_column: str, company_id,
    ) -> list[LineageEdgeRecord]:
        self.calls.append((source_id, src_column))
        return [e for e in self.edges if e.src_column == src_column]


class _FakeCatalogReader:
    """Test double for the L3 :class:`_CatalogReader` Protocol.

    L4's factory only needs ``list_tables_for_source`` (read the current
    snapshot). The pre-computed ``column_changes`` path bypasses this in
    Sub-wave B; the call still happens when no ``column_changes`` are
    pre-set so tests can verify the Optional-Effect path.
    """

    def __init__(self, sources: dict[str, list] | None = None) -> None:
        self.sources = sources or {}
        self.calls: list[tuple[str, str]] = []

    async def list_tables_for_source(
        self, *, company_id, source_id: str,
    ):
        self.calls.append(("source", source_id))
        return self.sources.get(source_id, [])

    async def list_candidate_targets(
        self, *, company_id, source_id: str,
    ):
        self.calls.append(("candidates", source_id))
        return self.sources.get(source_id, [])


async def _write_external_catalog_imported(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
    source_kind: str = "dbt",
    column_changes: list[dict] | None = None,
) -> None:
    """Drive a canonical ``external_catalog_imported`` PEVR cycle."""
    args: dict[str, Any] = {
        "source_id": source_id,
        "source_kind": source_kind,
        "snapshot_hash": "test-hash",
        "table_count": 1,
        "edge_count": 0,
        "metric_count": 0,
        "import_mode": "initial",
        "domain_id": str(uuid4()),
    }
    if column_changes:
        args["column_changes"] = column_changes
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "external_catalog_imported",
            "source_id": source_id,
            "ref_id": source_id,
            "reason": "test external_catalog_imported",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_external_catalog_imported",
            "args": args,
            "result_ref": source_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "external_catalog_imported", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "test external_catalog_imported",
        },
        quadrant="active_deterministic",
    )


def _fetch_schema_impact_proposed(rows: list[dict]) -> list[dict]:
    """Return execute rows for the ``schema_impact_proposed`` cycle."""
    return [
        r for r in rows
        if r["kind"] == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_schema_impact_proposed"
    ]


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_args_preserve_pre_l4_byte_identity() -> None:
    """``impact_service=None`` AND ``catalog_reader=None`` (defaults)
    → no ``schema_impact_proposed`` entries emitted even on triggers."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_schema_impact_discovery_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
        column_changes=[
            {"src_table": "src-001.public.orders",
             "src_column": "customer_id",
             "change_kind": "column_dropped",
             "old_type": "int", "new_type": None},
        ],
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_schema_impact_proposed(rows) == [], (
        "default factory args MUST preserve byte-identical pre-L4 behaviour "
        "(no schema_impact_proposed without a service+reader)"
    )


@pytest.mark.asyncio
async def test_catalog_reader_none_is_no_op() -> None:
    """``catalog_reader=None`` with wired service → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    service = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader(),
        ),
    )
    registry.register(
        make_schema_impact_discovery_reactivity(
            impact_service=service,
            catalog_reader=None,  # absent
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
        column_changes=[
            {"src_table": "src-001.public.orders",
             "src_column": "customer_id",
             "change_kind": "column_dropped",
             "old_type": "int", "new_type": None},
        ],
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_schema_impact_proposed(rows) == []


@pytest.mark.asyncio
async def test_impact_service_none_is_no_op() -> None:
    """``impact_service=None`` with wired reader → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    reader = _FakeCatalogReader(sources={"src-001": []})
    registry.register(
        make_schema_impact_discovery_reactivity(
            impact_service=None,  # absent
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
        column_changes=[
            {"src_table": "src-001.public.orders",
             "src_column": "customer_id",
             "change_kind": "column_dropped",
             "old_type": "int", "new_type": None},
        ],
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_schema_impact_proposed(rows) == []


# ---------------------------------------------------------------------------
# Fire path — external_catalog_imported with column_changes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_catalog_imported_with_drop_triggers_impact() -> None:
    """A column_dropped change with an L3 confirmed edge → one PEVR cycle."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    reader = _FakeCatalogReader(sources={"src-001": []})
    service = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
    )

    registry.register(
        make_schema_impact_discovery_reactivity(
            impact_service=service,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
        column_changes=[
            {"src_table": "src-001.public.orders",
             "src_column": "customer_id",
             "change_kind": "column_dropped",
             "old_type": "int", "new_type": None},
        ],
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_schema_impact_proposed(rows)
    assert len(proposed) == 1
    args = (proposed[0]["payload"] or {}).get("args") or {}
    assert args["source_id"] == "src-001"
    assert args["src_column"] == "customer_id"
    assert args["change_kind"] == "column_dropped"
    assert args["impact_kind"] == "tgt_column_orphaned"
    assert args["tgt_table_id"] == "dbt.marts.revenue"
    assert args["upstream_lineage_edge_id"] == "e1"
    assert args["strategy"] == "lineage_edge"


@pytest.mark.asyncio
async def test_multi_column_delta_fires_per_change() -> None:
    """Two changed columns in one snapshot → two PEVR cycles."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    e1 = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    e2 = LineageEdgeRecord(
        edge_id="e2",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    reader = _FakeCatalogReader(sources={"src-001": []})
    service = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader([e1, e2]),
        ),
    )

    registry.register(
        make_schema_impact_discovery_reactivity(
            impact_service=service,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
        column_changes=[
            {"src_table": "src-001.public.orders",
             "src_column": "customer_id",
             "change_kind": "column_dropped",
             "old_type": "int", "new_type": None},
            {"src_table": "src-001.public.orders",
             "src_column": "amount",
             "change_kind": "column_type_changed",
             "old_type": "int", "new_type": "numeric"},
        ],
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_schema_impact_proposed(rows)
    assert len(proposed) == 2
    src_columns = {
        (p["payload"] or {}).get("args", {}).get("src_column") for p in proposed
    }
    assert src_columns == {"customer_id", "amount"}


# ---------------------------------------------------------------------------
# Idempotency + quality filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_filter_suppresses_recent_re_propose() -> None:
    """A second trigger for the same (source, column, change_kind) within
    the propose window → idempotency_filter short-circuits."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    reader = _FakeCatalogReader(sources={"src-001": []})
    service = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
    )

    registry.register(
        make_schema_impact_discovery_reactivity(
            impact_service=service,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    change = {
        "src_table": "src-001.public.orders",
        "src_column": "customer_id",
        "change_kind": "column_dropped",
        "old_type": "int", "new_type": None,
    }
    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
        column_changes=[change],
    )
    await runner.run_once()
    first = _fetch_schema_impact_proposed(await ledger.fetch(_COMPANY_ID))
    assert len(first) == 1

    # Second fire with a fresh registry (bypasses NotRecentlyFired) +
    # same change → idempotency_filter blocks the re-propose.
    fresh_registry = ReactivityRegistry(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    fresh_registry.register(
        make_schema_impact_discovery_reactivity(
            impact_service=service,
            catalog_reader=reader,
        ),
    )
    fresh_runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=fresh_registry,
        poll_interval_s=0.01,
    )
    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
        column_changes=[change],
    )
    await fresh_runner.run_once()
    second = _fetch_schema_impact_proposed(await ledger.fetch(_COMPANY_ID))
    assert len(second) == 1, (
        f"idempotency_filter failed: expected 1 schema_impact_proposed "
        f"after re-trigger within window, got {len(second)}"
    )


@pytest.mark.asyncio
async def test_no_column_changes_means_no_fire() -> None:
    """external_catalog_imported without column_changes → no impacts."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="customer_id",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="customer_id",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    reader = _FakeCatalogReader(sources={"src-001": []})
    service = CompositeSchemaImpactService(
        lineage_edge=LineageEdgeImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
    )

    registry.register(
        make_schema_impact_discovery_reactivity(
            impact_service=service,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    # No column_changes → Sub-wave B falls back to walking the catalog,
    # which returns [] for now → no impacts.
    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_schema_impact_proposed(rows) == []
    # The catalog_reader IS reached (Sub-wave B's degradation path).
    assert ("source", "src-001") in reader.calls


@pytest.mark.asyncio
async def test_type_coercion_only_strategy_runs_alone() -> None:
    """type_coercion alone produces type_coercion_required on type changes."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    edge = LineageEdgeRecord(
        edge_id="e1",
        src_table_id="src-001.public.orders",
        src_column="amount",
        tgt_table_id="dbt.marts.revenue",
        tgt_column="amount",
        confidence=0.99,
        strategy="dbt_manifest",
    )
    reader = _FakeCatalogReader(sources={"src-001": []})
    service = CompositeSchemaImpactService(
        type_coercion=TypeCoercionImpactStrategy(
            lineage_edge_reader=_FakeReader([edge]),
        ),
    )

    registry.register(
        make_schema_impact_discovery_reactivity(
            impact_service=service,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
        column_changes=[
            {"src_table": "src-001.public.orders",
             "src_column": "amount",
             "change_kind": "column_type_changed",
             "old_type": "int", "new_type": "varchar"},
        ],
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_schema_impact_proposed(rows)
    assert len(proposed) == 1
    args = (proposed[0]["payload"] or {}).get("args") or {}
    assert args["impact_kind"] == "type_coercion_required"
    assert args["strategy"] == "type_coercion"
