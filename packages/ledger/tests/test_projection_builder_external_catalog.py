"""Projection-fold tests for catalog-mirror entries (Semantic Layer Wave 3, Task 1).

Pins the projection-builder contract for two new tools:

* ``emit_external_catalog_imported`` → ``projection_external_catalog``
* ``emit_external_lineage_imported`` → ``projection_external_lineage``

These tables are read by the ``/lake/catalog`` dashboard page; this test
guards the fold so the dashboard's read-side never goes stale relative
to the ledger source-of-truth.

The CatalogImportReactivity at
``packages/wormbase-catalog-mirror/src/wormbase_catalog_mirror/reactivities.py``
writes a PEVR cycle whose execute-payload carries
``tool="emit_external_catalog_imported"`` (or
``tool="emit_external_lineage_imported"``) + the canonical
``ExternalCatalogImportedPayload`` / ``ExternalLineageImportedPayload``
body under ``payload.args``. This test writes the same canonical PEVR
through ``write_primitive`` so the projection builder folds the entries
identically to a production write.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import build_projections
from wormbase_ledger.write_primitive import write_primitive


def _catalog_args(
    *,
    source_id: UUID,
    domain_id: UUID,
    source_kind: str = "dbt",
    snapshot_hash: str = "abc123",
    table_count: int = 8,
    edge_count: int = 8,
    metric_count: int = 0,
    import_mode: str = "initial",
) -> dict[str, object]:
    """Build the canonical execute-payload args for emit_external_catalog_imported."""
    return {
        "source_kind": source_kind,
        "source_id": str(source_id),
        "domain_id": str(domain_id),
        "snapshot_hash": snapshot_hash,
        "table_count": table_count,
        "edge_count": edge_count,
        "metric_count": metric_count,
        "import_mode": import_mode,
    }


def _lineage_args(
    *,
    source_id: UUID,
    edges: list[tuple[str, str]],
) -> dict[str, object]:
    """Build the canonical execute-payload args for emit_external_lineage_imported."""
    return {
        "source_id": str(source_id),
        # Pydantic serialises tuples as lists when crossing the JSON
        # boundary; mirror that here so the fold sees the same shape on
        # disk as in tests.
        "edges": [list(e) for e in edges],
    }


@pytest.mark.asyncio
async def test_external_catalog_imported_creates_projection_row(
    test_database_url: str,
) -> None:
    """One PEVR cycle → one projection_external_catalog row with the right shape."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()
    domain_id = uuid4()

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "external_catalog_imported",
                "ref_id": str(source_id),
                "reason": "catalog-mirror: external_catalog_imported",
                "proposed_by": "catalog_mirror",
            },
            execute_fn=lambda: {
                "tool": "emit_external_catalog_imported",
                "args": _catalog_args(
                    source_id=source_id,
                    domain_id=domain_id,
                    snapshot_hash="snap-abc123",
                    table_count=12,
                    edge_count=11,
                    metric_count=3,
                ),
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "catalog_recorded", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "external_catalog_imported observed",
            },
            quadrant="active_deterministic",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.external_catalog) == 1
    row = proj.external_catalog[0]
    assert row["company_id"] == company_id
    assert row["source_id"] == source_id
    assert row["domain_id"] == domain_id
    assert row["source_kind"] == "dbt"
    assert row["snapshot_hash"] == "snap-abc123"
    assert row["table_count"] == 12
    assert row["edge_count"] == 11
    assert row["metric_count"] == 3
    assert row["import_mode"] == "initial"
    # imported_at is the entry ts; just assert it's tz-aware (datetime).
    assert row["imported_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_external_catalog_imported_replay_is_idempotent(
    test_database_url: str,
) -> None:
    """Same (source_id, snapshot_hash) re-folds onto the same row id.

    A no-op refresh that re-emits the same snapshot_hash MUST collapse
    onto the same projection row id; only a genuine drift (different
    snapshot_hash) should create a new row. This pins the
    ``_external_catalog_uuid`` keying contract.
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()
    domain_id = uuid4()
    args = _catalog_args(
        source_id=source_id,
        domain_id=domain_id,
        snapshot_hash="snap-stable",
    )

    # Two PEVR cycles with the same snapshot_hash — first as "initial",
    # second as "refresh" (same hash → no-op refresh).
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "external_catalog_imported",
                "ref_id": str(source_id),
                "reason": "catalog-mirror: initial import",
                "proposed_by": "catalog_mirror",
            },
            execute_fn=lambda: {
                "tool": "emit_external_catalog_imported",
                "args": args,
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="active_deterministic",
        )

    refresh_args = dict(args, import_mode="refresh")
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "external_catalog_imported",
                "ref_id": str(source_id),
                "reason": "catalog-mirror: refresh (no drift)",
                "proposed_by": "catalog_mirror",
            },
            execute_fn=lambda: {
                "tool": "emit_external_catalog_imported",
                "args": refresh_args,
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="active_deterministic",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # Same snapshot_hash → single row, latest-wins for import_mode.
    assert len(proj.external_catalog) == 1
    row = proj.external_catalog[0]
    assert row["snapshot_hash"] == "snap-stable"
    assert row["import_mode"] == "refresh"


@pytest.mark.asyncio
async def test_external_catalog_drift_creates_new_row(
    test_database_url: str,
) -> None:
    """A different snapshot_hash for the same source → a NEW projection row.

    The /lake/catalog accessor reads the most-recent snapshot per
    source_id at read time; keeping both rows preserves the lineage of
    catalog-mirror snapshots over time. This pins the contract that
    drift is additive to the projection, not destructive.
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()
    domain_id = uuid4()

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "external_catalog_imported",
                "ref_id": str(source_id),
                "reason": "catalog-mirror: initial",
                "proposed_by": "catalog_mirror",
            },
            execute_fn=lambda: {
                "tool": "emit_external_catalog_imported",
                "args": _catalog_args(
                    source_id=source_id,
                    domain_id=domain_id,
                    snapshot_hash="hash-v1",
                ),
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="active_deterministic",
        )

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "external_catalog_imported",
                "ref_id": str(source_id),
                "reason": "catalog-mirror: drift",
                "proposed_by": "catalog_mirror",
            },
            execute_fn=lambda: {
                "tool": "emit_external_catalog_imported",
                "args": _catalog_args(
                    source_id=source_id,
                    domain_id=domain_id,
                    snapshot_hash="hash-v2",
                    table_count=14,  # 2 tables added
                    import_mode="refresh",
                ),
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="active_deterministic",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.external_catalog) == 2
    hashes = {r["snapshot_hash"] for r in proj.external_catalog}
    assert hashes == {"hash-v1", "hash-v2"}


@pytest.mark.asyncio
async def test_external_lineage_imported_creates_row_per_edge(
    test_database_url: str,
) -> None:
    """One PEVR cycle with N edges → N projection_external_lineage rows."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()
    edges = [
        ("source.raw.events", "model.staging.events"),
        ("model.staging.events", "model.marts.events_daily"),
        ("source.raw.users", "model.staging.users"),
    ]

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "external_lineage_imported",
                "ref_id": str(source_id),
                "reason": "catalog-mirror: external_lineage_imported",
                "proposed_by": "catalog_mirror",
            },
            execute_fn=lambda: {
                "tool": "emit_external_lineage_imported",
                "args": _lineage_args(source_id=source_id, edges=edges),
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="active_deterministic",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.external_lineage) == 3
    seen = {(r["upstream"], r["downstream"]) for r in proj.external_lineage}
    assert seen == set(edges)

    # Every row carries the same source_id + company_id.
    for row in proj.external_lineage:
        assert row["company_id"] == company_id
        assert row["source_id"] == source_id
        assert row["imported_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_external_lineage_replay_collapses_identical_edges(
    test_database_url: str,
) -> None:
    """Two imports with the same edge set → one row per edge (not two).

    Mirrors the catalog-table idempotency contract: deterministic per-edge
    id keyed on (company_id, source_id, upstream, downstream) means a
    no-op re-import doesn't double-count edges in /lake/catalog's
    lineage-count column.
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()
    edges = [
        ("upstream.a", "downstream.b"),
        ("upstream.c", "downstream.d"),
    ]

    for _ in range(2):
        async with session_scope(engine) as session:
            await write_primitive(
                session,
                company_id=company_id,
                propose={
                    "target_kind": "external_lineage_imported",
                    "ref_id": str(source_id),
                    "reason": "catalog-mirror: lineage re-import",
                    "proposed_by": "catalog_mirror",
                },
                execute_fn=lambda: {
                    "tool": "emit_external_lineage_imported",
                    "args": _lineage_args(source_id=source_id, edges=edges),
                    "result_ref": str(source_id),
                },
                verify_fn=lambda _r: {"checks": [], "passed": True},
                resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
                quadrant="active_deterministic",
            )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # Still exactly two rows — identical edges collapsed.
    assert len(proj.external_lineage) == 2


@pytest.mark.asyncio
async def test_external_catalog_projection_is_tenant_scoped(
    test_database_url: str,
) -> None:
    """Catalog entries in tenant A are not visible from tenant B's fold."""
    engine = get_engine(test_database_url)
    tenant_a = uuid4()
    tenant_b = uuid4()
    source_id = uuid4()
    domain_id = uuid4()

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=tenant_a,
            propose={
                "target_kind": "external_catalog_imported",
                "ref_id": str(source_id),
                "reason": "tenant A catalog import",
                "proposed_by": "catalog_mirror",
            },
            execute_fn=lambda: {
                "tool": "emit_external_catalog_imported",
                "args": _catalog_args(
                    source_id=source_id,
                    domain_id=domain_id,
                    snapshot_hash="tenant-a-hash",
                ),
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
            quadrant="active_deterministic",
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, tenant_a)
        proj_b = await build_projections(session, tenant_b)

    assert len(proj_a.external_catalog) == 1
    assert len(proj_b.external_catalog) == 0
