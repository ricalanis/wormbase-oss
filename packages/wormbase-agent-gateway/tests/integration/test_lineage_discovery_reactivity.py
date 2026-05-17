"""L3 Sub-wave B — Compounding-factory integration tests.

Pins the L3 lineage-discovery axis end-to-end through a real
``ReactivityRegistry`` + ``ReactivityRunner`` + ``InMemoryLedger``:

  * Fires on ``source_connected`` events.
  * Fires on ``external_catalog_imported`` events.
  * No-op when ``inference_service`` is None (Optional-Effect Injection
    case 9, absent path).
  * No-op when ``catalog_reader`` is None.
  * Quality filter: missing ``source_id`` → no fire.
  * Idempotency filter: re-proposing within window suppressed.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_agent_gateway.lineage import (
    CatalogTable,
    CompositeLineageInferenceService,
    NamingHeuristicStrategy,
)
from wormbase_agent_gateway.reactivities import (
    make_lineage_discovery_reactivity,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a0009")


class _FakeCatalogReader:
    """Test double: canned source-table + candidate-target lists."""

    def __init__(
        self,
        *,
        sources: dict[str, list[CatalogTable]] | None = None,
        candidates: dict[str, list[CatalogTable]] | None = None,
    ) -> None:
        self.sources = sources or {}
        self.candidates = candidates or {}
        self.calls: list[tuple[str, str]] = []

    async def list_tables_for_source(
        self, *, company_id: UUID, source_id: str,
    ) -> list[CatalogTable]:
        self.calls.append(("source", source_id))
        return self.sources.get(source_id, [])

    async def list_candidate_targets(
        self, *, company_id: UUID, source_id: str,
    ) -> list[CatalogTable]:
        self.calls.append(("candidates", source_id))
        return self.candidates.get(source_id, [])


async def _write_source_connected(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
) -> None:
    """Drive a canonical ``source_connected`` PEVR cycle."""
    args: dict[str, Any] = {
        "source_id": source_id,
        "connection_ref": "fixture",
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "source_connected",
            "source_id": source_id,
            "ref_id": source_id,
            "reason": "test source_connected",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_connected",
            "args": args,
            "result_ref": source_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "source_connected", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "test source_connected",
        },
        quadrant="active_deterministic",
    )


async def _write_external_catalog_imported(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
    source_kind: str = "dbt",
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


def _fetch_lineage_edge_proposed(rows: list[dict]) -> list[dict]:
    """Return execute rows for the ``lineage_edge_proposed`` cycle."""
    return [
        r for r in rows
        if r["kind"] == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_lineage_edge_proposed"
    ]


@pytest.mark.asyncio
async def test_default_args_preserve_subwave_a_byte_identity() -> None:
    """``inference_service=None`` AND ``catalog_reader=None`` (defaults)
    → no ``lineage_edge_proposed`` entries emitted even on triggers."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_lineage_discovery_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_source_connected(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_lineage_edge_proposed(rows) == [], (
        "default factory args MUST preserve byte-identical Sub-wave A "
        "behaviour (no lineage_edge_proposed without a service+reader)"
    )


@pytest.mark.asyncio
async def test_source_connected_triggers_inference_pass() -> None:
    """source_connected event + wired service → one
    ``lineage_edge_proposed`` PEVR cycle per inferred edge."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    source_id = "src-001"
    src_table = CatalogTable(
        table_id=f"{source_id}.public.orders",
        columns=("customer_id",),
        source_kind="postgres",
    )
    tgt_table = CatalogTable(
        table_id="src-002.public.customers",
        columns=("customer_id",),
        source_kind="postgres",
    )
    reader = _FakeCatalogReader(
        sources={source_id: [src_table]},
        candidates={source_id: [src_table, tgt_table]},
    )
    inference = CompositeLineageInferenceService(
        naming=NamingHeuristicStrategy(),
    )

    registry.register(
        make_lineage_discovery_reactivity(
            inference_service=inference,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_source_connected(
        ledger, company_id=_COMPANY_ID, source_id=source_id,
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    edges = _fetch_lineage_edge_proposed(rows)
    assert len(edges) == 1
    edge_args = (edges[0]["payload"] or {}).get("args") or {}
    assert edge_args["src_table_id"] == "src-001.public.orders"
    assert edge_args["tgt_table_id"] == "src-002.public.customers"
    assert edge_args["src_column"] == "customer_id"
    assert edge_args["strategy"] == "naming_heuristic"
    assert edge_args["confidence"] == 0.85
    # Inference invoked once per source
    assert ("source", source_id) in reader.calls


@pytest.mark.asyncio
async def test_external_catalog_imported_also_triggers() -> None:
    """external_catalog_imported event triggers inference too (OR predicate)."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    source_id = "dbt-prod"
    src_table = CatalogTable(
        table_id=f"{source_id}.staging.orders",
        columns=("customer_id",),
        source_kind="dbt",
    )
    other = CatalogTable(
        table_id="snowflake-prod.public.customers",
        columns=("customer_id",),
        source_kind="snowflake",
    )
    reader = _FakeCatalogReader(
        sources={source_id: [src_table]},
        candidates={source_id: [src_table, other]},
    )
    inference = CompositeLineageInferenceService(
        naming=NamingHeuristicStrategy(),
    )

    registry.register(
        make_lineage_discovery_reactivity(
            inference_service=inference,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id=source_id,
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    edges = _fetch_lineage_edge_proposed(rows)
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_catalog_reader_none_is_no_op() -> None:
    """``catalog_reader=None`` with wired inference → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    inference = CompositeLineageInferenceService(
        naming=NamingHeuristicStrategy(),
    )
    registry.register(
        make_lineage_discovery_reactivity(
            inference_service=inference,
            catalog_reader=None,  # absent
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_source_connected(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_lineage_edge_proposed(rows) == []


@pytest.mark.asyncio
async def test_inference_service_none_is_no_op() -> None:
    """``inference_service=None`` with wired reader → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    src_table = CatalogTable(
        table_id="src-001.public.orders",
        columns=("customer_id",),
        source_kind="postgres",
    )
    reader = _FakeCatalogReader(
        sources={"src-001": [src_table]},
        candidates={"src-001": [src_table]},
    )
    registry.register(
        make_lineage_discovery_reactivity(
            inference_service=None,  # absent
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_source_connected(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_lineage_edge_proposed(rows) == []


@pytest.mark.asyncio
async def test_idempotency_filter_suppresses_recent_re_propose() -> None:
    """A second source_connected for the same source within the propose
    window → idempotency_filter short-circuits, no duplicate emissions."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    source_id = "src-001"
    src_table = CatalogTable(
        table_id=f"{source_id}.public.orders",
        columns=("customer_id",),
        source_kind="postgres",
    )
    tgt_table = CatalogTable(
        table_id="src-002.public.customers",
        columns=("customer_id",),
        source_kind="postgres",
    )
    reader = _FakeCatalogReader(
        sources={source_id: [src_table]},
        candidates={source_id: [src_table, tgt_table]},
    )
    inference = CompositeLineageInferenceService(
        naming=NamingHeuristicStrategy(),
    )

    # First fire — emits one edge.
    registry.register(
        make_lineage_discovery_reactivity(
            inference_service=inference,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )
    await _write_source_connected(
        ledger, company_id=_COMPANY_ID, source_id=source_id,
    )
    await runner.run_once()
    first = _fetch_lineage_edge_proposed(await ledger.fetch(_COMPANY_ID))
    assert len(first) == 1

    # Second fire with a fresh registry (bypasses NotRecentlyFired) +
    # same source → idempotency_filter blocks, no new emissions.
    fresh_registry = ReactivityRegistry(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    fresh_registry.register(
        make_lineage_discovery_reactivity(
            inference_service=inference,
            catalog_reader=reader,
        ),
    )
    fresh_runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=fresh_registry,
        poll_interval_s=0.01,
    )
    await _write_source_connected(
        ledger, company_id=_COMPANY_ID, source_id=source_id,
    )
    await fresh_runner.run_once()
    second = _fetch_lineage_edge_proposed(await ledger.fetch(_COMPANY_ID))
    assert len(second) == 1, (
        f"idempotency_filter failed: expected 1 lineage_edge_proposed "
        f"after re-trigger within window, got {len(second)}"
    )


@pytest.mark.asyncio
async def test_quality_filter_rejects_missing_source_id() -> None:
    """Trigger entry with empty source_id → quality_filter rejects, no fire."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    src_table = CatalogTable(
        table_id="src-001.public.orders",
        columns=("customer_id",),
        source_kind="postgres",
    )
    reader = _FakeCatalogReader(
        sources={"src-001": [src_table]},
        candidates={"src-001": [src_table]},
    )
    inference = CompositeLineageInferenceService(
        naming=NamingHeuristicStrategy(),
    )
    registry.register(
        make_lineage_discovery_reactivity(
            inference_service=inference,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    # Drive a PEVR cycle with an empty source_id in args (defensive — the
    # canonical emitter would never produce this, but the quality_filter
    # must be defensible against malformed entries).
    await ledger.write(
        company_id=_COMPANY_ID,
        propose={
            "target_kind": "source_connected",
            "ref_id": "",
            "reason": "malformed test entry",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_connected",
            "args": {"source_id": "", "connection_ref": "fixture"},
            "result_ref": "",
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "source_connected", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "malformed",
        },
        quadrant="active_deterministic",
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_lineage_edge_proposed(rows) == []
    # Reader never called — quality_filter short-circuited.
    assert reader.calls == []
