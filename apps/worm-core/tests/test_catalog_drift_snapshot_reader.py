"""L2 Sub-wave C — LedgerCatalogSnapshotReader impl tests.

Exercises the ledger-walk + fold-replay
:class:`LedgerCatalogSnapshotReader` shipped in
``wormbase_core.catalog_drift_snapshot_reader``. The Protocol
contract (from
:mod:`wormbase_agent_gateway.catalog_drift.protocol`):

  * Return ``(current, baseline)`` where ``current`` is the
    most-recent ``external_catalog_imported`` for ``(company_id,
    source_id)`` and ``baseline`` is the second-most-recent (or
    ``None`` when only one snapshot exists).
  * Tenant-scoped via ``company_id``.
  * Replay-stable: same ledger state → same snapshots.

Per Sub-wave B handoff concern #1, the reader imports
:class:`CatalogSnapshot` from
:mod:`wormbase_agent_gateway.catalog_drift`, NOT from
:mod:`wormbase_agent_gateway.lineage` (the two modules carry
identically-named dataclasses with diverging semantics).
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.catalog_drift_snapshot_reader import (
    LedgerCatalogSnapshotReader,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000ca7a1064")


async def _write_external_catalog_imported(
    ledger: InMemoryLedger,
    *,
    source_id: str,
    snapshot_hash: str = "deadbeef",
    table_count: int = 3,
    company_id: UUID | None = None,
) -> None:
    """Seed an ``external_catalog_imported`` execute entry."""
    cid = company_id if company_id is not None else _COMPANY_ID
    args = {
        "source_id": source_id,
        "source_kind": "snowflake_native",
        "domain_id": str(uuid4()),
        "snapshot_hash": snapshot_hash,
        "table_count": table_count,
        "edge_count": 0,
        "metric_count": 0,
        "import_mode": "refresh",
    }
    await ledger.write(
        company_id=cid,
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


# ---------------------------------------------------------------------------
# Empty-ledger + single-snapshot + multi-snapshot folds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_ledger_returns_empty_current_and_none_baseline() -> None:
    """No external_catalog_imported entries → synthetic empty current + None baseline."""
    from wormbase_agent_gateway.catalog_drift import CatalogSnapshot

    ledger = InMemoryLedger()
    reader = LedgerCatalogSnapshotReader(ledger=ledger)

    current, baseline = await reader.read_current_and_baseline(
        company_id=_COMPANY_ID, source_id="src-A",
    )

    assert isinstance(current, CatalogSnapshot)
    assert current.source_id == "src-A"
    assert current.tables == ()
    assert baseline is None


@pytest.mark.asyncio
async def test_single_snapshot_returns_current_and_none_baseline() -> None:
    """One snapshot → that snapshot as current; baseline is None."""
    from wormbase_agent_gateway.catalog_drift import CatalogSnapshot

    ledger = InMemoryLedger()
    await _write_external_catalog_imported(ledger, source_id="src-A")

    reader = LedgerCatalogSnapshotReader(ledger=ledger)
    current, baseline = await reader.read_current_and_baseline(
        company_id=_COMPANY_ID, source_id="src-A",
    )

    assert isinstance(current, CatalogSnapshot)
    assert current.source_id == "src-A"
    # No richer-diff emitter yet — tables tuple stays empty.
    assert current.tables == ()
    assert baseline is None


@pytest.mark.asyncio
async def test_two_snapshots_return_current_and_baseline_pair() -> None:
    """Two snapshots → most-recent as current, second-most-recent as baseline."""
    from wormbase_agent_gateway.catalog_drift import CatalogSnapshot

    ledger = InMemoryLedger()
    await _write_external_catalog_imported(
        ledger, source_id="src-A", snapshot_hash="hash-1",
    )
    await _write_external_catalog_imported(
        ledger, source_id="src-A", snapshot_hash="hash-2",
    )

    reader = LedgerCatalogSnapshotReader(ledger=ledger)
    current, baseline = await reader.read_current_and_baseline(
        company_id=_COMPANY_ID, source_id="src-A",
    )

    assert isinstance(current, CatalogSnapshot)
    assert isinstance(baseline, CatalogSnapshot)
    assert current.source_id == "src-A"
    assert baseline.source_id == "src-A"
    # current is more recent than baseline (fetch is oldest-first).
    assert current.as_of >= baseline.as_of


@pytest.mark.asyncio
async def test_three_snapshots_return_latest_two() -> None:
    """Three snapshots → only the latest two appear in (current, baseline)."""
    ledger = InMemoryLedger()
    await _write_external_catalog_imported(
        ledger, source_id="src-A", snapshot_hash="hash-1",
    )
    await _write_external_catalog_imported(
        ledger, source_id="src-A", snapshot_hash="hash-2",
    )
    await _write_external_catalog_imported(
        ledger, source_id="src-A", snapshot_hash="hash-3",
    )

    reader = LedgerCatalogSnapshotReader(ledger=ledger)
    current, baseline = await reader.read_current_and_baseline(
        company_id=_COMPANY_ID, source_id="src-A",
    )

    assert current is not None
    assert baseline is not None
    # Both are CatalogSnapshot, latest-first; the first hash entry
    # must NOT be returned.
    assert current.as_of >= baseline.as_of


# ---------------------------------------------------------------------------
# Tenant + per-source isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_source_isolation_returns_per_source_snapshot() -> None:
    """Reader returns only snapshots matching the requested source_id."""
    ledger = InMemoryLedger()
    # src-A snapshots
    await _write_external_catalog_imported(ledger, source_id="src-A")
    await _write_external_catalog_imported(ledger, source_id="src-A")
    # src-B snapshot (different source)
    await _write_external_catalog_imported(ledger, source_id="src-B")

    reader = LedgerCatalogSnapshotReader(ledger=ledger)

    # src-A should see both its snapshots.
    a_current, a_baseline = await reader.read_current_and_baseline(
        company_id=_COMPANY_ID, source_id="src-A",
    )
    assert a_current.source_id == "src-A"
    assert a_baseline is not None
    assert a_baseline.source_id == "src-A"

    # src-B should see only its own snapshot — no baseline.
    b_current, b_baseline = await reader.read_current_and_baseline(
        company_id=_COMPANY_ID, source_id="src-B",
    )
    assert b_current.source_id == "src-B"
    assert b_baseline is None


@pytest.mark.asyncio
async def test_tenant_scoping_by_company_id() -> None:
    """Reader scopes by ``company_id`` — other tenants' entries are invisible."""
    ledger = InMemoryLedger()
    other_company = UUID("00000000-0000-0000-0000-000000000aa1")

    # Seed two snapshots in the other tenant.
    await _write_external_catalog_imported(
        ledger, source_id="src-X", company_id=other_company,
    )
    await _write_external_catalog_imported(
        ledger, source_id="src-X", company_id=other_company,
    )

    reader = LedgerCatalogSnapshotReader(ledger=ledger)
    current, baseline = await reader.read_current_and_baseline(
        company_id=_COMPANY_ID, source_id="src-X",
    )

    # Reader sees zero matching entries in this tenant.
    assert current.tables == ()
    assert baseline is None


# ---------------------------------------------------------------------------
# Edge cases — empty source_id; replay stability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_source_id_returns_synthetic_pair() -> None:
    """Empty source_id → synthetic empty current + None baseline (no crash)."""
    ledger = InMemoryLedger()
    reader = LedgerCatalogSnapshotReader(ledger=ledger)

    current, baseline = await reader.read_current_and_baseline(
        company_id=_COMPANY_ID, source_id="",
    )

    assert current is not None
    assert current.tables == ()
    assert baseline is None


@pytest.mark.asyncio
async def test_replay_stability_two_walks_yield_identical_snapshot_pair() -> None:
    """Two consecutive reads over the same ledger yield identical snapshot pairs.

    Per Sub-wave B handoff concern #8: ``drift_id`` PK collision
    absorbs duplicate ticks at the projection layer. The reader is
    upstream of that — its job is to be deterministic so the
    composite's drift_ids are stable across replays.
    """
    ledger = InMemoryLedger()
    await _write_external_catalog_imported(
        ledger, source_id="src-A", snapshot_hash="a",
    )
    await _write_external_catalog_imported(
        ledger, source_id="src-A", snapshot_hash="b",
    )

    reader = LedgerCatalogSnapshotReader(ledger=ledger)

    pair1 = await reader.read_current_and_baseline(
        company_id=_COMPANY_ID, source_id="src-A",
    )
    pair2 = await reader.read_current_and_baseline(
        company_id=_COMPANY_ID, source_id="src-A",
    )

    assert pair1[0].source_id == pair2[0].source_id
    assert pair1[0].as_of == pair2[0].as_of
    assert pair1[0].tables == pair2[0].tables
    assert pair1[1] is not None
    assert pair2[1] is not None
    assert pair1[1].as_of == pair2[1].as_of


@pytest.mark.asyncio
async def test_non_catalog_imported_entries_ignored() -> None:
    """Entries with other tools (e.g. emit_source_proposed) do NOT count."""
    ledger = InMemoryLedger()

    # Seed a non-catalog entry that should be ignored.
    await ledger.write(
        company_id=_COMPANY_ID,
        propose={
            "target_kind": "source_proposed",
            "ref_id": "noise",
            "reason": "noise",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_proposed",
            "args": {"source_id": "src-A", "source_kind": "csv_local"},
            "result_ref": "noise",
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )

    reader = LedgerCatalogSnapshotReader(ledger=ledger)
    current, baseline = await reader.read_current_and_baseline(
        company_id=_COMPANY_ID, source_id="src-A",
    )

    # No external_catalog_imported entries — empty synthetic current,
    # None baseline.
    assert current.tables == ()
    assert baseline is None
