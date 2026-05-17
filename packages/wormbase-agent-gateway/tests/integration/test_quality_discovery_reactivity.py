"""L7 Sub-wave B — Compounding-factory integration tests.

Pins the L7 quality-check axis end-to-end through a real
``ReactivityRegistry`` + ``ReactivityRunner`` + ``InMemoryLedger``:

  * Fires on ``source_connected`` events.
  * Fires on ``external_catalog_imported`` events.
  * No-op when ``proposal_service`` is None (Optional-Effect Injection
    case 10, absent path).
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

from wormbase_agent_gateway.quality import (
    CatalogTable,
    CompositeQualityProposalService,
    SchemaPatternStrategy,
)
from wormbase_agent_gateway.reactivities import (
    make_quality_discovery_reactivity,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a000c")


class _FakeCatalogReader:
    """Test double: canned source-table list (mirrors L3 fake)."""

    def __init__(
        self,
        *,
        sources: dict[str, list[CatalogTable]] | None = None,
    ) -> None:
        self.sources = sources or {}
        self.calls: list[tuple[str, str]] = []

    async def list_tables_for_source(
        self, *, company_id: UUID, source_id: str,
    ) -> list[CatalogTable]:
        self.calls.append(("source", source_id))
        return self.sources.get(source_id, [])

    async def list_candidate_targets(
        self, *, company_id: UUID, source_id: str,
    ) -> list[CatalogTable]:
        # The quality axis only walks list_tables_for_source; this
        # method exists to satisfy the L3-style _CatalogReader Protocol
        # signature when callers share one reader between L3 + L7.
        self.calls.append(("candidates", source_id))
        return self.sources.get(source_id, [])


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


def _fetch_quality_check_proposed(rows: list[dict]) -> list[dict]:
    """Return execute rows for the ``quality_check_proposed`` cycle."""
    return [
        r for r in rows
        if r["kind"] == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_quality_check_proposed"
    ]


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_args_preserve_pre_l7_byte_identity() -> None:
    """``proposal_service=None`` AND ``catalog_reader=None`` (defaults)
    → no ``quality_check_proposed`` entries emitted even on triggers."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_quality_discovery_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_source_connected(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_quality_check_proposed(rows) == [], (
        "default factory args MUST preserve byte-identical pre-L7 "
        "behaviour (no quality_check_proposed without a service+reader)"
    )


@pytest.mark.asyncio
async def test_catalog_reader_none_is_no_op() -> None:
    """``catalog_reader=None`` with wired service → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    service = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )
    registry.register(
        make_quality_discovery_reactivity(
            proposal_service=service,
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
    assert _fetch_quality_check_proposed(rows) == []


@pytest.mark.asyncio
async def test_proposal_service_none_is_no_op() -> None:
    """``proposal_service=None`` with wired reader → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    src_table = CatalogTable(
        table_id="src-001.public.orders",
        columns=("customer_id",),
        source_kind="postgres",
    )
    reader = _FakeCatalogReader(sources={"src-001": [src_table]})
    registry.register(
        make_quality_discovery_reactivity(
            proposal_service=None,  # absent
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
    assert _fetch_quality_check_proposed(rows) == []


# ---------------------------------------------------------------------------
# Fire path — both source-trigger predicates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_connected_triggers_proposal_pass() -> None:
    """source_connected event + wired service → one
    ``quality_check_proposed`` PEVR cycle per inferred check."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    source_id = "src-001"
    src_table = CatalogTable(
        table_id=f"{source_id}.public.orders",
        columns=("customer_id",),
        source_kind="postgres",
    )
    reader = _FakeCatalogReader(sources={source_id: [src_table]})
    service = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )

    registry.register(
        make_quality_discovery_reactivity(
            proposal_service=service,
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
    proposed = _fetch_quality_check_proposed(rows)
    # SchemaPatternStrategy proposes a unique check on ``customer_id``
    # (id-naming heuristic). Exactly one check expected.
    assert len(proposed) == 1
    args = (proposed[0]["payload"] or {}).get("args") or {}
    assert args["table_id"] == f"{source_id}.public.orders"
    assert args["column"] == "customer_id"
    assert args["check_kind"] == "unique"
    assert args["strategy"] == "schema_pattern"
    assert args["confidence"] == 0.80
    # Inference invoked for the source
    assert ("source", source_id) in reader.calls


@pytest.mark.asyncio
async def test_external_catalog_imported_also_triggers() -> None:
    """external_catalog_imported event triggers proposals too (OR predicate)."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    source_id = "dbt-prod"
    src_table = CatalogTable(
        table_id=f"{source_id}.staging.orders",
        columns=("customer_id",),
        source_kind="dbt",
    )
    reader = _FakeCatalogReader(sources={source_id: [src_table]})
    service = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )

    registry.register(
        make_quality_discovery_reactivity(
            proposal_service=service,
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
    proposed = _fetch_quality_check_proposed(rows)
    assert len(proposed) >= 1


# ---------------------------------------------------------------------------
# Idempotency + quality filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_filter_suppresses_recent_re_propose() -> None:
    """A second trigger for the same source within the propose window
    → idempotency_filter short-circuits, no duplicate emissions."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    source_id = "src-001"
    src_table = CatalogTable(
        table_id=f"{source_id}.public.orders",
        columns=("customer_id",),
        source_kind="postgres",
    )
    reader = _FakeCatalogReader(sources={source_id: [src_table]})
    service = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )

    registry.register(
        make_quality_discovery_reactivity(
            proposal_service=service,
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
    first = _fetch_quality_check_proposed(await ledger.fetch(_COMPANY_ID))
    assert len(first) == 1

    # Second fire with a fresh registry (bypasses NotRecentlyFired) +
    # same source → idempotency_filter blocks the re-propose.
    fresh_registry = ReactivityRegistry(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    fresh_registry.register(
        make_quality_discovery_reactivity(
            proposal_service=service,
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
    second = _fetch_quality_check_proposed(await ledger.fetch(_COMPANY_ID))
    assert len(second) == 1, (
        f"idempotency_filter failed: expected 1 quality_check_proposed "
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
    reader = _FakeCatalogReader(sources={"src-001": [src_table]})
    service = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )
    registry.register(
        make_quality_discovery_reactivity(
            proposal_service=service,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    # Drive a PEVR cycle with an empty source_id (defensive — canonical
    # emitter never produces this, but quality_filter must be defensible).
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
    assert _fetch_quality_check_proposed(rows) == []
    # Reader never called — quality_filter short-circuited.
    assert reader.calls == []


@pytest.mark.asyncio
async def test_inference_dedupes_across_multiple_source_tables() -> None:
    """Same check proposed by two source-tables in the same fire → dedup.

    Defensive test: if two CatalogTables share a table_id + column +
    check_kind (e.g. duplicate fixture entries), the promotion-action
    must dedup by check_id before writing.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    source_id = "src-001"
    tbl = CatalogTable(
        table_id=f"{source_id}.public.orders",
        columns=("customer_id",),
        source_kind="postgres",
    )
    reader = _FakeCatalogReader(
        sources={source_id: [tbl, tbl]},  # listed twice
    )
    service = CompositeQualityProposalService(
        schema_pattern=SchemaPatternStrategy(),
    )

    registry.register(
        make_quality_discovery_reactivity(
            proposal_service=service,
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
    proposed = _fetch_quality_check_proposed(rows)
    # Still exactly 1 — same check_id dedup'd.
    assert len(proposed) == 1
