"""EvidenceSource: read-only over projection_notebooks + projection_data_products."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.schema import metadata as ledger_metadata
from wormbase_lake_surfaces.evidence_source import EvidenceSource
from wormbase_lake_maintainer.protocols import MaintainableSource


async def _engine_with_evidence_tables():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(ledger_metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_evidence_source_implements_maintainable() -> None:
    engine = await _engine_with_evidence_tables()
    src = EvidenceSource(
        id=uuid4(), company_id=uuid4(), classification="internal",
        domain=None, owner=None, engine=engine,
    )
    assert isinstance(src, MaintainableSource)


@pytest.mark.asyncio
async def test_evidence_source_has_no_discover_method() -> None:
    """C5: EvidenceSource has no acquisition surface."""
    src = EvidenceSource(
        id=uuid4(), company_id=uuid4(), classification="internal",
        domain=None, owner=None,
        engine=await _engine_with_evidence_tables(),
    )
    assert not hasattr(src, "discover")
    assert not hasattr(src, "profile")
    assert not hasattr(src, "sample")


@pytest.mark.asyncio
async def test_staleness_flags_when_no_recent_publishes() -> None:
    engine = await _engine_with_evidence_tables()
    company = uuid4()
    long_ago = datetime.now(UTC) - timedelta(days=10)
    from wormbase_ledger.schema import projection_data_products
    async with engine.begin() as conn:
        await conn.execute(insert(projection_data_products), [dict(
            data_product_id=uuid4(),
            tenant_id=company,
            name="DP1",
            kind="chart",
            status="generated",
            requested_by_person_id=uuid4(),
            domain_id=None,
            latest_run_seq=1,
            generated_at=long_ago,
            content_hash=None,
            contents_uri=None,
            last_updated_seq=1,
        )])
    src = EvidenceSource(
        id=uuid4(), company_id=company, classification="internal",
        domain=None, owner=None, engine=engine,
        staleness_sla_hours=24.0,
    )
    report = await src.staleness_signal()
    assert report.stale is True
    assert report.last_seen is not None


@pytest.mark.asyncio
async def test_lineage_health_reports_healthy_with_no_evidence() -> None:
    engine = await _engine_with_evidence_tables()
    src = EvidenceSource(
        id=uuid4(), company_id=uuid4(), classification="internal",
        domain=None, owner=None, engine=engine,
    )
    report = await src.lineage_health()
    assert report.healthy is True
    assert report.broken_edges == []


@pytest.mark.asyncio
async def test_detect_drift_no_baseline_returns_no_drift() -> None:
    engine = await _engine_with_evidence_tables()
    src = EvidenceSource(
        id=uuid4(), company_id=uuid4(), classification="internal",
        domain=None, owner=None, engine=engine,
    )
    report = await src.detect_drift()
    assert report.drifted is False
