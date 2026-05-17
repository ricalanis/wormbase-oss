"""Drift-detection + initial-import Reactivity end-to-end via the W5a runner.

Exercises the catalog-mirror Reactivities through the real W5a
``ReactivityRegistry`` + ``ReactivityRunner`` + ``InMemoryLedger``
stack — no mocks. The runner reads new ledger entries, dispatches them
through the registry, and the registry runs ``predicate ∧ condition``
before calling ``Reactivity.fire``. Each Reactivity's ``fire`` writes
its PEVR cycle back through the same ledger handle, so the test
inspects the ledger's entry list to assert outcomes.

Two scenarios:

* ``test_initial_import_emits_external_catalog_imported`` — a seed
  ``source_profiled`` entry triggers ``CatalogImportReactivity``;
  exactly one ``external_catalog_imported`` PEVR cycle lands.
* ``test_second_tick_no_drift_no_emit`` — after the initial import,
  running the runner again on the same fixture produces no further
  ``external_catalog_imported`` or ``external_catalog_drift_detected``
  rows, because the source's snapshot_hash is unchanged.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_catalog_mirror.implementations.dbt_manifest import (
    DbtManifestCatalogSource,
)
from wormbase_catalog_mirror.reactivities import (
    make_catalog_mirror_reactivities,
)


# Stable UUID so test runs hash-equivalent across replays.
COMPANY = UUID("00000000-0000-0000-0000-00000000ca70")
SOURCE_ID = "src-jaffle-shop"
DOMAIN_ID = "domain-finance"
NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)


def _fixture_path() -> Path:
    """Locate the jaffle_shop manifest under the package's tests/fixtures."""
    return (
        Path(__file__).parent.parent / "fixtures" / "jaffle_shop_manifest.json"
    )


async def _seed_source_profiled(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
    at: datetime = NOW,
) -> None:
    """Write a minimal ``source_profiled`` execute entry so the catalog-
    mirror Reactivities have something to react to.

    Matches the shape that ``SourceBuilder.profile`` emits in production
    (apps/worm-core/src/wormbase_core/source_builder.py:321-366) — the
    refresh-trigger predicate inspects ``payload.tool``, which we set
    to ``emit_source_profiled`` here.
    """
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "source_profiled",
            "ref_id": source_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_profiled",
            "args": {
                "source_id": source_id,
                "domain_id": DOMAIN_ID,
                "row_count": 0,
                "column_count": 0,
                "schema_hash": "deadbeef",
                "profile_ref": "profile-ref-test",
            },
            "result_ref": source_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep", "rationale": "test seed",
        },
        timestamp=at,
        quadrant="active_deterministic",
    )


def _count_kind(rows: list[dict], *, tool_suffix: str) -> int:
    """Count execute rows whose ``payload.tool`` ends with ``tool_suffix``.

    Reactivity-emitted rows land as execute envelopes with
    ``tool='emit_<kind>'``. This walks the ledger fetch result and
    counts matches.
    """
    n = 0
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool") or ""
        if tool.endswith(tool_suffix):
            n += 1
    return n


@pytest.mark.asyncio
async def test_initial_import_emits_external_catalog_imported() -> None:
    """First runner pass on a fresh ledger emits external_catalog_imported."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=COMPANY)

    src = DbtManifestCatalogSource(manifest_path=_fixture_path())
    reactivities = make_catalog_mirror_reactivities(
        source_id=SOURCE_ID,
        domain_id=DOMAIN_ID,
        catalog_source=src,
        secrets={},
    )
    for r in reactivities:
        registry.register(r)

    # Seed the trigger entry: a source_profiled execute row.
    await _seed_source_profiled(
        ledger, company_id=COMPANY, source_id=SOURCE_ID,
    )

    runner = ReactivityRunner(
        ledger=ledger, company_id=COMPANY, registry=registry,
        poll_interval_s=0.0,
    )
    fired = await runner.run_once()

    # At least one Reactivity fired (the import one).
    assert fired >= 1, "expected CatalogImportReactivity to fire on first pass"

    rows = await ledger.fetch(COMPANY)
    imported = _count_kind(rows, tool_suffix="emit_external_catalog_imported")
    assert imported == 1, (
        f"expected exactly one external_catalog_imported; got {imported}"
    )
    # The drift reactivity must not fire on the first pass — there is
    # no baseline yet, so it returns no-op.
    drifted = _count_kind(
        rows, tool_suffix="emit_external_catalog_drift_detected",
    )
    assert drifted == 0


@pytest.mark.asyncio
async def test_second_tick_no_drift_no_emit() -> None:
    """Two runner passes against an unchanged fixture produce one import
    + zero drift entries.

    The initial import landed on the first pass; the second pass
    re-walks the trigger entries (and the new external_catalog_imported
    entry itself, which is also a refresh-trigger kind) but no further
    external_catalog_imported or drift entries should be emitted because:
      * Import is short-circuited by the "prior import exists" check
        inside fire().
      * Drift is short-circuited by snapshot_hash equality.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=COMPANY)
    src = DbtManifestCatalogSource(manifest_path=_fixture_path())
    reactivities = make_catalog_mirror_reactivities(
        source_id=SOURCE_ID,
        domain_id=DOMAIN_ID,
        catalog_source=src,
        secrets={},
    )
    for r in reactivities:
        registry.register(r)

    await _seed_source_profiled(
        ledger, company_id=COMPANY, source_id=SOURCE_ID,
    )

    runner = ReactivityRunner(
        ledger=ledger, company_id=COMPANY, registry=registry,
        poll_interval_s=0.0,
    )
    await runner.run_once()

    rows = await ledger.fetch(COMPANY)
    first_imported = _count_kind(
        rows, tool_suffix="emit_external_catalog_imported",
    )
    first_drift = _count_kind(
        rows, tool_suffix="emit_external_catalog_drift_detected",
    )
    assert first_imported == 1
    assert first_drift == 0

    # Second pass: the runner cursor has advanced past the seed and the
    # initial-import rows, but the dispatch path is symmetric so re-firing
    # would be a regression. Re-seed a fresh trigger to give the runner
    # a new row to dispatch on.
    await _seed_source_profiled(
        ledger,
        company_id=COMPANY,
        source_id=SOURCE_ID,
        at=NOW.replace(hour=13),
    )
    await runner.run_once()

    rows = await ledger.fetch(COMPANY)
    second_imported = _count_kind(
        rows, tool_suffix="emit_external_catalog_imported",
    )
    second_drift = _count_kind(
        rows, tool_suffix="emit_external_catalog_drift_detected",
    )
    assert second_imported == 1, (
        "second tick must not re-emit external_catalog_imported when a "
        "prior import exists"
    )
    assert second_drift == 0, (
        "second tick on unchanged snapshot_hash must not emit drift"
    )
