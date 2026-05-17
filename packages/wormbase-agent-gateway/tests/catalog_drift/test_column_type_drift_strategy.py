"""L2 Sub-wave B — ColumnTypeDriftStrategy tests.

Pins:

  * Empty baseline (None) → no proposals.
  * Empty-upstream posture (columns=()) → no proposals (honest stub).
  * When type info present + type changes → ``column_type_changed``.
  * Same name, same type → no proposal.
  * One side missing type info → no proposal (insufficient signal).
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
    ColumnTypeDriftStrategy,
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
                columns=(CatalogColumn(name="id", type="bigint"),),
            ),
        ),
    )
    strategy = ColumnTypeDriftStrategy()
    assert await strategy.propose(
        company_id=_COMPANY, current=current, baseline=None,
    ) == []


@pytest.mark.asyncio
async def test_empty_upstream_honest_stub() -> None:
    """``columns == ()`` on both sides → empty-upstream stub.

    Pin: today's external_catalog_imported has no per-column structure;
    ColumnType returns ``[]`` immediately.
    """
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(CatalogTable(table_id="src-1.public.users", columns=()),),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(CatalogTable(table_id="src-1.public.users", columns=()),),
    )
    strategy = ColumnTypeDriftStrategy()
    assert await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    ) == []


@pytest.mark.asyncio
async def test_type_change_emits_proposal() -> None:
    """Column type changes → ``column_type_changed`` proposal."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(
                    CatalogColumn(name="email", type="varchar(100)"),
                ),
            ),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(
                    CatalogColumn(name="email", type="varchar(255)"),
                ),
            ),
        ),
    )
    strategy = ColumnTypeDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.drift_kind == "column_type_changed"
    assert p.column == "email"
    assert p.table_id == "src-1.public.users"
    assert p.before == {"type": "varchar(100)"}
    assert p.after == {"type": "varchar(255)"}
    assert p.strategy == "column_type"
    assert p.confidence == 0.80
    assert p.evidence["before_type"] == "varchar(100)"
    assert p.evidence["after_type"] == "varchar(255)"


@pytest.mark.asyncio
async def test_same_type_no_proposal() -> None:
    """Same column name + same type → no proposal."""
    cols = (CatalogColumn(name="email", type="varchar(255)"),)
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(CatalogTable(table_id="src-1.public.users", columns=cols),),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(CatalogTable(table_id="src-1.public.users", columns=cols),),
    )
    strategy = ColumnTypeDriftStrategy()
    assert await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    ) == []


@pytest.mark.asyncio
async def test_one_side_missing_type_no_proposal() -> None:
    """One side ``type is None`` → no proposal (insufficient signal).

    The payload validator on ``column_type_changed`` requires both
    ``before`` and ``after`` non-None. The strategy mirrors that
    invariant.
    """
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="email", type=None),),
            ),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="email", type="text"),),
            ),
        ),
    )
    strategy = ColumnTypeDriftStrategy()
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_column_only_in_current_no_proposal() -> None:
    """Column absent in baseline — ColumnSet handles it; ColumnType skips."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="id", type="bigint"),),
            ),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(
                    CatalogColumn(name="id", type="bigint"),
                    CatalogColumn(name="email", type="varchar(255)"),
                ),
            ),
        ),
    )
    strategy = ColumnTypeDriftStrategy()
    # Only column_added (ColumnSet's job); no type-change emissions.
    proposals = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert proposals == []


@pytest.mark.asyncio
async def test_drift_id_deterministic() -> None:
    """Same inputs → same drift_id."""
    baseline = CatalogSnapshot(
        source_id="src-1", as_of=_earlier(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="email", type="varchar(100)"),),
            ),
        ),
    )
    current = CatalogSnapshot(
        source_id="src-1", as_of=_now(),
        tables=(
            CatalogTable(
                table_id="src-1.public.users",
                columns=(CatalogColumn(name="email", type="varchar(255)"),),
            ),
        ),
    )
    strategy = ColumnTypeDriftStrategy()
    a = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    b = await strategy.propose(
        company_id=_COMPANY, current=current, baseline=baseline,
    )
    assert a[0].drift_id == b[0].drift_id
