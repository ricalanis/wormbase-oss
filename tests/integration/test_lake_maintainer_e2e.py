"""LakeMaintainer end-to-end: connect → register → fire → audit."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from wormbase_ledger.ledger_api import InMemoryLedger
from wormbase_lake_surfaces.external_source import AcquirableSourceImpl
from wormbase_lake_maintainer.registry import (
    SourceRegistry,
    wire_maintenance_for_source,
)
from wormbase_reactivities.registry import ReactivityRegistry


def _fake_connector_with_drift():
    """First profile() returns hash A; subsequent calls return hash B."""
    class _C:
        kind = "csv_local"
        capability = {"discover", "profile", "sample"}
        classification_hints: list = []
        status = "production"
        status_note = ""

        def __init__(self) -> None:
            self._calls = 0

        async def authenticate(self, secrets):
            return {"h": 1}

        async def discover(self, handle):
            return []

        async def profile(self, handle, resource_id):
            from wormbase_lake_surfaces.types import Profile
            self._calls += 1
            return Profile(
                row_count=10,
                column_count=2,
                columns=[{"name": "id"}, {"name": "v"}],
                schema_hash=("0x" + "01" * 64) if self._calls == 1 else ("0x" + "02" * 64),
            )

        async def sample(self, handle, resource_id, n):
            return b""

        def watch(self, handle, resource_id):
            async def _e():
                if False:
                    yield None
            return _e()
    return _C()


@pytest.mark.asyncio
async def test_e2e_drift_detection_emits_signal() -> None:
    company = uuid4()
    ledger = InMemoryLedger()
    reactivity_registry = ReactivityRegistry(
        ledger=ledger, company_id=company,
    )
    source_registry = SourceRegistry(company_id=company)

    # 1. Build the AcquirableSourceImpl with a known baseline.
    src = AcquirableSourceImpl(
        id=uuid4(), family="external", classification="internal",
        domain=None, owner=None,
        connector=_fake_connector_with_drift(),
        auth_handle={"h": 1},
        baseline_schema_hash="0x" + "01" * 64,
        last_seen=datetime.now(UTC),
        primary_resource_id="default",
    )

    # 2. Establish baseline by calling profile() once (sets connector
    #    call counter to 1; baseline hash matches).
    profile1 = await src.profile("default")
    assert profile1.schema_hash == "0x" + "01" * 64

    # 3. Wire maintenance — registers 4 Reactivities with W5a registry.
    reactivities = await wire_maintenance_for_source(
        source=src,
        source_registry=source_registry,
        reactivity_registry=reactivity_registry,
    )
    assert len(reactivities) == 4

    # 4. Confirm the Reactivities so they're active (handle the case
    #    where register() defaults to active and confirm() raises).
    admin_uuid = uuid4()
    for r in reactivities:
        try:
            await reactivity_registry.confirm(r.id, confirmed_by=admin_uuid)
        except Exception:
            pass  # Already active from register(initial_state="active")

    # 5. Simulate a source_profiled ledger entry via the PEVR-cycle
    #    write API. The Reactivities are listening for any of the
    #    refresh-trigger entry kinds; emit_source_profiled is one.
    await ledger.write(
        company_id=company,
        propose={
            "target_kind": "source_profiled",
            "ref_id": str(src.id),
            "reason": "test trigger",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_profiled",
            "args": {"source_id": str(src.id)},
            "result_ref": str(src.id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "test",
        },
        timestamp=datetime.now(UTC),
        quadrant="active_deterministic",
    )

    # 6. Fetch the entries and dispatch each through the registry.
    #    The runner does this in production; we drive it directly so
    #    the test stays deterministic.
    entries = await ledger.fetch(company)
    fired_ids: list[str] = []
    for entry in entries:
        ids = await reactivity_registry.dispatch(entry)
        fired_ids.extend(ids)

    # 7. The drift Reactivity should have fired (current hash B vs.
    #    baseline hash A). Staleness is a no-op (last_seen is recent).
    assert any("drift" in fid for fid in fired_ids), (
        f"expected a drift_* reactivity to fire; fired_ids={fired_ids}"
    )

    # 8. The ledger should now contain a source_drift_detected execute entry.
    rows = await ledger.fetch(company)
    drift_signals = [
        r for r in rows
        if (r.get("payload") or {}).get("tool") == "emit_source_drift_detected"
    ]
    assert len(drift_signals) >= 1, (
        f"expected emit_source_drift_detected in ledger; rows={[r.get('payload', {}).get('tool') for r in rows]}"
    )


@pytest.mark.asyncio
async def test_e2e_one_source_per_family_all_register() -> None:
    """C1+C3+C5 confirmed at the integration layer: 4 Sources × 4 Reactivities = 16."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from wormbase_ledger.schema import metadata as ledger_metadata
    from wormbase_lake_surfaces.conversation_source import ConversationSource
    from wormbase_lake_surfaces.evidence_source import EvidenceSource

    company = uuid4()
    ledger = InMemoryLedger()
    reactivity_registry = ReactivityRegistry(
        ledger=ledger, company_id=company,
    )
    source_registry = SourceRegistry(company_id=company)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(ledger_metadata.create_all)

    sources = [
        AcquirableSourceImpl(
            id=uuid4(), family="external", classification="internal",
            domain=None, owner=None,
            connector=_fake_connector_with_drift(),
            auth_handle={"h": 1},
        ),
        AcquirableSourceImpl(
            id=uuid4(), family="filedrop", classification="internal",
            domain=None, owner=None,
            connector=_fake_connector_with_drift(),
            auth_handle={"h": 1},
        ),
        ConversationSource(
            id=uuid4(), company_id=company, classification="internal",
            domain=None, owner=None, engine=engine,
        ),
        EvidenceSource(
            id=uuid4(), company_id=company, classification="internal",
            domain=None, owner=None, engine=engine,
        ),
    ]

    total = 0
    for src in sources:
        reactivities = await wire_maintenance_for_source(
            source=src,
            source_registry=source_registry,
            reactivity_registry=reactivity_registry,
        )
        total += len(reactivities)

    assert total == 16  # 4 Sources × 4 Reactivities each
    listed = await source_registry.list_sources()
    assert len(listed) == 4
    families = {s.family for s in listed}
    assert families == {"external", "filedrop", "conversation", "evidence"}
