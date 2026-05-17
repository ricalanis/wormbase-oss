"""MaintainableSource methods on AcquirableSourceImpl."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from wormbase_lake_surfaces.external_source import AcquirableSourceImpl
from wormbase_lake_maintainer.protocols import MaintainableSource


_HASH_A = "0x" + "01" * 64
_HASH_B = "0x" + "02" * 64


class _FakeConnectorWithProfile:
    """Connector whose profile() returns a deterministic schema_hash (str)."""

    kind = "csv_local"
    capability = {"discover", "profile", "sample"}
    classification_hints: list = []
    status = "production"
    status_note = ""

    def __init__(self, schema_hash: str) -> None:
        self._schema_hash = schema_hash

    async def authenticate(self, secrets):
        return {"h": 1}

    async def discover(self, handle):
        return []

    async def profile(self, handle, resource_id):
        from wormbase_lake_surfaces.types import Profile
        return Profile(
            row_count=10,
            column_count=2,
            columns=[{"name": "id"}, {"name": "v"}],
            schema_hash=self._schema_hash,
        )

    async def sample(self, handle, resource_id, n):
        return b""

    def watch(self, handle, resource_id):
        async def _empty():
            if False:
                yield None
        return _empty()


def _make_src(
    *,
    schema_hash: str,
    baseline_hash: str | None = None,
    last_seen: datetime | None = None,
    classification: str = "internal",
) -> AcquirableSourceImpl:
    src = AcquirableSourceImpl(
        id=uuid4(),
        family="external",
        classification=classification,
        domain=None,
        owner=None,
        connector=_FakeConnectorWithProfile(schema_hash=schema_hash),
        auth_handle={"h": 1},
        baseline_schema_hash=baseline_hash,
        last_seen=last_seen,
        primary_resource_id="default",
    )
    return src


@pytest.mark.asyncio
async def test_external_implements_maintainable_protocol() -> None:
    src = _make_src(schema_hash=_HASH_A)
    assert isinstance(src, MaintainableSource)


@pytest.mark.asyncio
async def test_detect_drift_returns_no_drift_when_hash_matches() -> None:
    src = _make_src(schema_hash=_HASH_A, baseline_hash=_HASH_A)
    report = await src.detect_drift()
    assert report.drifted is False
    assert report.baseline_hash == _HASH_A
    assert report.current_hash == _HASH_A


@pytest.mark.asyncio
async def test_detect_drift_flags_when_hash_changes() -> None:
    src = _make_src(schema_hash=_HASH_B, baseline_hash=_HASH_A)
    report = await src.detect_drift()
    assert report.drifted is True
    assert "schema_hash changed" in report.reason


@pytest.mark.asyncio
async def test_detect_drift_no_baseline_returns_no_drift() -> None:
    src = _make_src(schema_hash=_HASH_B, baseline_hash=None)
    report = await src.detect_drift()
    assert report.drifted is False
    assert report.reason == "no baseline yet"


@pytest.mark.asyncio
async def test_staleness_signal_flags_when_last_seen_old() -> None:
    long_ago = datetime.now(UTC) - timedelta(hours=48)
    src = _make_src(schema_hash=_HASH_A, last_seen=long_ago)
    report = await src.staleness_signal()
    assert report.stale is True
    assert report.last_seen == long_ago


@pytest.mark.asyncio
async def test_staleness_signal_clean_when_recent() -> None:
    recent = datetime.now(UTC) - timedelta(hours=2)
    src = _make_src(schema_hash=_HASH_A, last_seen=recent)
    report = await src.staleness_signal()
    assert report.stale is False


@pytest.mark.asyncio
async def test_refresh_classification_returns_current_when_unchanged() -> None:
    src = _make_src(schema_hash=_HASH_A, classification="internal")
    update = await src.refresh_classification()
    assert update.classification == "internal"
    assert update.updated is False


@pytest.mark.asyncio
async def test_lineage_health_returns_healthy_for_unbroken_source() -> None:
    src = _make_src(schema_hash=_HASH_A)
    report = await src.lineage_health()
    assert report.healthy is True
    assert report.broken_edges == []
