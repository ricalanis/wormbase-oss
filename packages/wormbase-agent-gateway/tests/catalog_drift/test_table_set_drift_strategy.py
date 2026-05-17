"""L2 Sub-wave B — TableSetDriftStrategy tests.

Pins:

  * Empty baseline (None) → no proposals (first snapshot is the baseline).
  * Empty current — every baseline table emits ``table_removed``.
  * Empty baseline.tables (but baseline present) — every current table
    emits ``table_added``.
  * Identical snapshots → no proposals.
  * Mixed adds + removes → both kinds emitted.
  * Productive day-1 — works on bare ``table_id`` fields (no
    ``columns`` data needed).
  * Drift_id is deterministic on ``(source_id, table_id, drift_kind,
    before, after)``.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from wormbase_agent_gateway.catalog_drift import (
    CatalogSnapshot,
    CatalogTable,
    TableSetDriftStrategy,
)


_COMPANY = UUID("00000000-0000-0000-0000-000000000a02")


def _now() -> datetime:
    return datetime.now(UTC)


def _earlier() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_no_baseline_returns_empty() -> None:
    """First snapshot for the source → no drift to report."""
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(CatalogTable(table_id="src-1.public.users"),),
    )
    strategy = TableSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=None,
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_identical_snapshots_return_empty() -> None:
    """Same table-id sets → no proposals."""
    tables = (
        CatalogTable(table_id="src-1.public.users"),
        CatalogTable(table_id="src-1.public.orders"),
    )
    current = CatalogSnapshot(source_id="src-1", as_of=_now(), tables=tables)
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(), tables=tables,
    )
    strategy = TableSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_one_table_added() -> None:
    """A single new table → one ``table_added`` proposal."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(CatalogTable(table_id="src-1.public.users"),),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(table_id="src-1.public.users"),
            CatalogTable(table_id="src-1.public.orders"),
        ),
    )
    strategy = TableSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.drift_kind == "table_added"
    assert p.table_id == "src-1.public.orders"
    assert p.column is None
    assert p.before is None
    assert p.after == {"table_id": "src-1.public.orders"}
    assert p.strategy == "table_set"
    assert p.source_id == "src-1"
    assert p.confidence == 0.9
    assert p.evidence["added_table_id"] == "src-1.public.orders"


@pytest.mark.asyncio
async def test_one_table_removed() -> None:
    """A single dropped table → one ``table_removed`` proposal."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(table_id="src-1.public.users"),
            CatalogTable(table_id="src-1.public.orders"),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(CatalogTable(table_id="src-1.public.users"),),
    )
    strategy = TableSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.drift_kind == "table_removed"
    assert p.table_id == "src-1.public.orders"
    assert p.before == {"table_id": "src-1.public.orders"}
    assert p.after is None
    assert p.evidence["removed_table_id"] == "src-1.public.orders"


@pytest.mark.asyncio
async def test_empty_current_all_baseline_tables_removed() -> None:
    """``current`` has no tables → every baseline table emits removed."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(table_id="src-1.public.a"),
            CatalogTable(table_id="src-1.public.b"),
        ),
    )
    current = CatalogSnapshot(source_id="src-1", as_of=_now(), tables=())
    strategy = TableSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) == 2
    kinds = {p.drift_kind for p in proposals}
    assert kinds == {"table_removed"}
    tids = {p.table_id for p in proposals}
    assert tids == {"src-1.public.a", "src-1.public.b"}


@pytest.mark.asyncio
async def test_empty_baseline_tables_all_current_tables_added() -> None:
    """``baseline.tables == ()`` but baseline present → all current → added."""
    baseline = CatalogSnapshot(source_id="src-1", as_of=_earlier(), tables=())
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(table_id="src-1.public.a"),
            CatalogTable(table_id="src-1.public.b"),
        ),
    )
    strategy = TableSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) == 2
    kinds = {p.drift_kind for p in proposals}
    assert kinds == {"table_added"}


@pytest.mark.asyncio
async def test_mixed_added_and_removed() -> None:
    """Both adds and removes → both proposal kinds emitted."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(table_id="src-1.public.users"),
            CatalogTable(table_id="src-1.public.legacy"),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(table_id="src-1.public.users"),
            CatalogTable(table_id="src-1.public.orders"),
        ),
    )
    strategy = TableSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) == 2
    kinds = sorted(p.drift_kind for p in proposals)
    assert kinds == ["table_added", "table_removed"]
    by_kind = {p.drift_kind: p for p in proposals}
    assert by_kind["table_added"].table_id == "src-1.public.orders"
    assert by_kind["table_removed"].table_id == "src-1.public.legacy"


@pytest.mark.asyncio
async def test_drift_id_deterministic_across_invocations() -> None:
    """Same inputs → same drift_id (replay-stable)."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(CatalogTable(table_id="src-1.public.users"),),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(table_id="src-1.public.users"),
            CatalogTable(table_id="src-1.public.orders"),
        ),
    )
    strategy = TableSetDriftStrategy()
    proposals_a = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    proposals_b = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert proposals_a[0].drift_id == proposals_b[0].drift_id


@pytest.mark.asyncio
async def test_productive_with_bare_table_ids_no_columns() -> None:
    """Productive day-1 — works on bare ``table_id`` fields (no columns).

    Pin per Sub-wave A handoff: ``external_catalog_imported`` carries
    ``added_table_ids`` / ``removed_table_ids`` (tuples present today)
    but no per-column structure. TableSet must work on bare table ids.
    """
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        # bare table — columns=()
        tables=(CatalogTable(table_id="src-1.public.users", columns=()),),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(table_id="src-1.public.users", columns=()),
            CatalogTable(table_id="src-1.public.orders", columns=()),
        ),
    )
    strategy = TableSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) == 1
    assert proposals[0].drift_kind == "table_added"
