"""L3 Sub-wave C — LedgerCatalogReader tests.

Pins the production CatalogReader's behaviour against the
``external_catalog_imported`` + ``external_lineage_imported`` ledger
entries emitted by the wormbase-catalog-mirror Reactivity. The reader
synthesizes ``CatalogTable``-shaped dicts that the lineage
inference service's strategies consume via Protocol structural typing.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.lineage_catalog_reader import (
    LedgerCatalogReader,
    LedgerDbtManifestReader,
    NoopSampler,
)


_COMPANY_A = UUID("00000000-0000-0000-0000-0000000c0001")
_COMPANY_B = UUID("00000000-0000-0000-0000-0000000c0002")


async def _emit_external_catalog_imported(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
    source_kind: str = "dbt",
) -> None:
    """Drive a minimal ``external_catalog_imported`` PEVR cycle."""
    args: dict[str, Any] = {
        "source_kind": source_kind,
        "source_id": source_id,
        "domain_id": "general",
        "snapshot_hash": "test-hash",
        "table_count": 0,
        "edge_count": 0,
        "metric_count": 0,
        "import_mode": "initial",
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "external_catalog_imported",
            "ref_id": source_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_external_catalog_imported",
            "args": args,
            "result_ref": source_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


async def _emit_external_lineage_imported(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
    edges: list[tuple[str, str]],
) -> None:
    """Drive a minimal ``external_lineage_imported`` PEVR cycle."""
    args: dict[str, Any] = {
        "source_id": source_id,
        "edges": list(edges),
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "external_lineage_imported",
            "ref_id": source_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_external_lineage_imported",
            "args": args,
            "result_ref": source_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


async def test_empty_catalog_returns_empty_lists() -> None:
    """No mirrored entries → both reader methods return ``[]``."""
    ledger = InMemoryLedger()
    reader = LedgerCatalogReader(ledger=ledger)
    src_tables = await reader.list_tables_for_source(
        company_id=_COMPANY_A, source_id="unknown",
    )
    assert src_tables == []
    candidates = await reader.list_candidate_targets(
        company_id=_COMPANY_A, source_id="unknown",
    )
    assert candidates == []


async def test_list_tables_for_source_reads_external_lineage_imported() -> None:
    """Tables for a source come from the edges of its lineage entries."""
    ledger = InMemoryLedger()
    await _emit_external_catalog_imported(
        ledger, company_id=_COMPANY_A, source_id="src-a", source_kind="dbt",
    )
    await _emit_external_lineage_imported(
        ledger,
        company_id=_COMPANY_A,
        source_id="src-a",
        edges=[
            ("raw.events", "stg.events"),
            ("stg.events", "mart.daily_events"),
        ],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY_A, source_id="src-a",
    )
    table_ids = {t.table_id for t in tables}
    assert table_ids == {
        "raw.events",
        "stg.events",
        "mart.daily_events",
    }
    # Source_kind should be propagated from external_catalog_imported.
    assert all(t.source_kind == "dbt" for t in tables)
    # Columns are empty (catalog mirror does not yet emit column lists).
    assert all(t.columns == () for t in tables)


async def test_list_candidate_targets_excludes_triggering_source() -> None:
    """Candidates come from OTHER sources, never the triggering source's own tables."""
    ledger = InMemoryLedger()
    # Source A — Snowflake (the triggering source)
    await _emit_external_catalog_imported(
        ledger, company_id=_COMPANY_A, source_id="src-a",
        source_kind="snowflake",
    )
    await _emit_external_lineage_imported(
        ledger,
        company_id=_COMPANY_A,
        source_id="src-a",
        edges=[("ACME.RAW.X", "ACME.STG.X")],
    )
    # Source B — dbt (candidates)
    await _emit_external_catalog_imported(
        ledger, company_id=_COMPANY_A, source_id="src-b",
        source_kind="dbt",
    )
    await _emit_external_lineage_imported(
        ledger,
        company_id=_COMPANY_A,
        source_id="src-b",
        edges=[
            ("dbt.raw.events", "dbt.stg.events"),
            ("dbt.stg.events", "dbt.mart.daily"),
        ],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    candidates = await reader.list_candidate_targets(
        company_id=_COMPANY_A, source_id="src-a",
    )
    candidate_ids = {t.table_id for t in candidates}
    assert candidate_ids == {
        "dbt.raw.events",
        "dbt.stg.events",
        "dbt.mart.daily",
    }
    # Source A's own tables MUST NOT appear in the candidate set.
    assert "ACME.RAW.X" not in candidate_ids
    assert "ACME.STG.X" not in candidate_ids
    # source_kind for candidates is set from the OWNING source's
    # external_catalog_imported, so dbt for all candidates here.
    assert all(t.source_kind == "dbt" for t in candidates)


async def test_list_candidate_targets_respects_max_targets() -> None:
    """``max_targets`` upper-bounds the candidate count + ordering is deterministic."""
    ledger = InMemoryLedger()
    edges = [(f"src.tbl_{i:03d}", f"dst.tbl_{i:03d}") for i in range(50)]
    await _emit_external_catalog_imported(
        ledger, company_id=_COMPANY_A, source_id="src-b",
        source_kind="dbt",
    )
    await _emit_external_lineage_imported(
        ledger, company_id=_COMPANY_A, source_id="src-b", edges=edges,
    )

    reader = LedgerCatalogReader(ledger=ledger)
    bounded = await reader.list_candidate_targets(
        company_id=_COMPANY_A, source_id="src-a", max_targets=10,
    )
    assert len(bounded) == 10
    # Deterministic sort (table_id alphabetical) for replay stability.
    bounded_ids = [t.table_id for t in bounded]
    assert bounded_ids == sorted(bounded_ids)


async def test_tenant_isolation_on_candidate_enumeration() -> None:
    """Candidates from another tenant must not leak into the result."""
    ledger = InMemoryLedger()
    # Tenant A
    await _emit_external_catalog_imported(
        ledger, company_id=_COMPANY_A, source_id="src-a", source_kind="dbt",
    )
    await _emit_external_lineage_imported(
        ledger,
        company_id=_COMPANY_A,
        source_id="src-other",
        edges=[("tenantA.tbl_1", "tenantA.tbl_2")],
    )
    # Tenant B has a totally different source set
    await _emit_external_catalog_imported(
        ledger, company_id=_COMPANY_B, source_id="src-x", source_kind="dbt",
    )
    await _emit_external_lineage_imported(
        ledger,
        company_id=_COMPANY_B,
        source_id="src-other-b",
        edges=[("tenantB.tbl_1", "tenantB.tbl_2")],
    )

    reader = LedgerCatalogReader(ledger=ledger)
    a_candidates = await reader.list_candidate_targets(
        company_id=_COMPANY_A, source_id="src-a",
    )
    a_ids = {t.table_id for t in a_candidates}
    # Tenant B's tables must NOT appear.
    assert "tenantB.tbl_1" not in a_ids
    assert "tenantB.tbl_2" not in a_ids
    # Tenant A's tables (from a different source than the triggering
    # source) DO appear.
    assert "tenantA.tbl_1" in a_ids
    assert "tenantA.tbl_2" in a_ids


async def test_ledger_dbt_manifest_reader_lifts_refs_from_edges() -> None:
    """LedgerDbtManifestReader resolves get_refs_for_model() from edges."""
    ledger = InMemoryLedger()
    await _emit_external_lineage_imported(
        ledger,
        company_id=_COMPANY_A,
        source_id="src-dbt",
        edges=[
            ("model.staging.events", "model.marts.daily_events"),
            ("model.raw.events", "model.staging.events"),
            ("model.dim.users", "model.marts.daily_events"),
        ],
    )
    reader = LedgerDbtManifestReader(ledger=ledger, company_id=_COMPANY_A)
    refs = await reader.get_refs_for_model("model.marts.daily_events")
    assert sorted(refs) == ["model.dim.users", "model.staging.events"]
    # get_source_refs returns empty (catalog mirror does not split ref/source)
    assert await reader.get_source_refs("model.marts.daily_events") == []


async def test_noop_sampler_returns_empty_sets() -> None:
    """NoopSampler is the honest-stub fallback — empty samples always."""
    sampler = NoopSampler()
    assert await sampler.sample_column("any_table", "any_column", 1000) == set()
    assert await sampler.estimate_table_size("any_table") == 0


async def test_returns_catalog_table_dataclass_shape() -> None:
    """Returned objects satisfy the CatalogTable structural shape."""
    ledger = InMemoryLedger()
    await _emit_external_catalog_imported(
        ledger, company_id=_COMPANY_A, source_id="src-a", source_kind="snowflake",
    )
    await _emit_external_lineage_imported(
        ledger,
        company_id=_COMPANY_A,
        source_id="src-a",
        edges=[("schema.t1", "schema.t2")],
    )
    reader = LedgerCatalogReader(ledger=ledger)
    tables = await reader.list_tables_for_source(
        company_id=_COMPANY_A, source_id="src-a",
    )
    assert tables
    head = tables[0]
    assert hasattr(head, "table_id")
    assert hasattr(head, "columns")
    assert hasattr(head, "source_kind")
    assert hasattr(head, "metadata")
    assert head.metadata == {}
