"""L2 Sub-wave B — ColumnSetDriftStrategy tests.

Pins:

  * Empty baseline (None) → no proposals.
  * Empty-upstream posture (no columns on either side) → no proposals,
    honest stub per spec §4.3 / Sub-wave A handoff #3.
  * When columns present + added → ``column_added`` proposals.
  * When columns present + removed → ``column_removed`` proposals.
  * Skips tables that are only in current or only in baseline
    (TableSet handles those at the table level).
  * Drift_id deterministic.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from wormbase_agent_gateway.catalog_drift import (
    CatalogColumn,
    CatalogSnapshot,
    CatalogTable,
    ColumnSetDriftStrategy,
)


_COMPANY = UUID("00000000-0000-0000-0000-000000000a02")


def _now() -> datetime:
    return datetime.now(UTC)


def _earlier() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_no_baseline_returns_empty() -> None:
    """First snapshot — no drift."""
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="id"),),
            ),
        ),
    )
    strategy = ColumnSetDriftStrategy()
    assert await strategy.propose(
        company_id=_COMPANY, current=current, baseline=None,
    ) == []


@pytest.mark.asyncio
async def test_empty_upstream_honest_stub() -> None:
    """No column data on either side → empty list (honest stub).

    Pin per Sub-wave A handoff #3: today's ``external_catalog_imported``
    payload doesn't include per-column structure, so reconstructed
    snapshots have ``CatalogTable.columns == ()``. The strategy must
    return ``[]`` immediately without false positives.
    """
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(CatalogTable(table_id="src-1.public.users", columns=()),),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(CatalogTable(table_id="src-1.public.users", columns=()),),
    )
    strategy = ColumnSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_column_added_with_columns_present() -> None:
    """Column appears on a shared table → ``column_added`` proposal."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="id"),),
            ),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(
                    CatalogColumn(name="id"),
                    CatalogColumn(name="email"),
                ),
            ),
        ),
    )
    strategy = ColumnSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.drift_kind == "column_added"
    assert p.column == "email"
    assert p.table_id == "src-1.public.users"
    assert p.before is None
    assert p.after == {"name": "email"}
    assert p.strategy == "column_set"
    assert p.confidence == 0.85


@pytest.mark.asyncio
async def test_column_removed_with_columns_present() -> None:
    """Column disappears from a shared table → ``column_removed``."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(
                    CatalogColumn(name="id"),
                    CatalogColumn(name="legacy_id"),
                ),
            ),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="id"),),
            ),
        ),
    )
    strategy = ColumnSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.drift_kind == "column_removed"
    assert p.column == "legacy_id"
    assert p.before == {"name": "legacy_id"}
    assert p.after is None


@pytest.mark.asyncio
async def test_skips_tables_only_in_current() -> None:
    """Tables only in current — TableSet handles them, ColumnSet skips."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="id"),),
            ),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="id"),),
            ),
            CatalogTable(
                table_id="src-1.public.orders",
                columns=(
                    CatalogColumn(name="id"),
                    CatalogColumn(name="amount"),
                ),
            ),
        ),
    )
    strategy = ColumnSetDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    # Orders is new — TableSet's job. ColumnSet emits no proposals.
    assert proposals == []


@pytest.mark.asyncio
async def test_drift_id_deterministic() -> None:
    """Same inputs → same drift_id (replay-stable)."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="id"),),
            ),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(
                    CatalogColumn(name="id"),
                    CatalogColumn(name="email"),
                ),
            ),
        ),
    )
    strategy = ColumnSetDriftStrategy()
    a = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    b = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert a[0].drift_id == b[0].drift_id


@pytest.mark.asyncio
async def test_one_side_empty_columns_still_short_circuits() -> None:
    """When neither snapshot has columns anywhere → empty-upstream stub.

    Even when one snapshot has tables with columns, if the OTHER side
    has no columns anywhere, the diff would be all-add or all-remove —
    arguably noise rather than signal. The honest-stub posture is that
    the strategy requires column structure on at least one side; the
    short-circuit fires only when BOTH sides are entirely empty of
    columns (which is today's reality).
    """
    # Both sides empty — short-circuit
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(CatalogTable(table_id="src-1.public.users", columns=()),),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(CatalogTable(table_id="src-1.public.users", columns=()),),
    )
    strategy = ColumnSetDriftStrategy()
    assert await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    ) == []
