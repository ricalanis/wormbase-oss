"""wire_catalog_for_source — per-source registration shape.

Verifies the per-source wire's contract:

* Takes ONE upstream_mirror Source and registers two Reactivities for
  it on the W5a registry (one import, one drift) — matches the
  lake-maintainer per-source pattern.
* Source duck-typed via ``id``, ``domain_id``, ``catalog_source``,
  optional ``secrets``.
* Reactivities are byte-identical to those produced by
  ``make_catalog_mirror_reactivities`` directly — the wire is glue,
  not transformation.

The boot-time ``wire_catalog_for_install`` shape was removed in Wave 1
cleanup 1a (2026-05-11); per-source dispatch happens from
``source_builder.SourceBuilder.on_source_connected``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry

from wormbase_catalog_mirror.implementations.dbt_manifest import (
    DbtManifestCatalogSource,
)
from wormbase_catalog_mirror.wires import wire_catalog_for_source


COMPANY = UUID("00000000-0000-0000-0000-00000000ca71")


@dataclass
class _StubUpstreamMirrorSource:
    """Per-Source record exposing the fields wire_catalog_for_source reads."""

    id: str
    domain_id: str
    catalog_source: Any
    secrets: dict[str, str]


def _fixture_path() -> Path:
    return (
        Path(__file__).parent.parent / "fixtures" / "jaffle_shop_manifest.json"
    )


@pytest.mark.asyncio
async def test_wire_registers_two_reactivities_for_one_source() -> None:
    """One upstream_mirror source → two registered Reactivities."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=COMPANY)
    src = _StubUpstreamMirrorSource(
        id="src-jaffle",
        domain_id="domain-finance",
        catalog_source=DbtManifestCatalogSource(manifest_path=_fixture_path()),
        secrets={},
    )

    registered = await wire_catalog_for_source(
        source=src,
        ledger=ledger,
        reactivity_registry=registry,
    )
    assert len(registered) == 2
    ids = sorted(r.id for r in registered)
    assert ids == [
        "catalog-mirror.drift.src-jaffle",
        "catalog-mirror.import.src-jaffle",
    ]
    # Registry sees them too.
    registry_ids = sorted(rec.id for rec in registry.list())
    assert "catalog-mirror.drift.src-jaffle" in registry_ids
    assert "catalog-mirror.import.src-jaffle" in registry_ids


@pytest.mark.asyncio
async def test_wire_handles_missing_secrets_attribute() -> None:
    """Source without a secrets attribute defaults to empty dict."""

    class _MinimalSource:
        id = "src-jaffle"
        domain_id = "domain-finance"
        catalog_source = DbtManifestCatalogSource(
            manifest_path=_fixture_path(),
        )

    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=COMPANY)

    registered = await wire_catalog_for_source(
        source=_MinimalSource(),
        ledger=ledger,
        reactivity_registry=registry,
    )
    assert len(registered) == 2
    ids = sorted(r.id for r in registered)
    assert ids == [
        "catalog-mirror.drift.src-jaffle",
        "catalog-mirror.import.src-jaffle",
    ]


@pytest.mark.asyncio
async def test_wire_registers_independently_for_two_sources() -> None:
    """Two separate calls register two distinct source-scoped Reactivity pairs."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=COMPANY)
    src1 = _StubUpstreamMirrorSource(
        id="src-jaffle-1",
        domain_id="domain-finance",
        catalog_source=DbtManifestCatalogSource(manifest_path=_fixture_path()),
        secrets={},
    )
    src2 = _StubUpstreamMirrorSource(
        id="src-jaffle-2",
        domain_id="domain-product",
        catalog_source=DbtManifestCatalogSource(manifest_path=_fixture_path()),
        secrets={},
    )

    r1 = await wire_catalog_for_source(
        source=src1, ledger=ledger, reactivity_registry=registry,
    )
    r2 = await wire_catalog_for_source(
        source=src2, ledger=ledger, reactivity_registry=registry,
    )
    assert len(r1) == 2
    assert len(r2) == 2
    all_ids = sorted(r.id for r in r1 + r2)
    assert all_ids == [
        "catalog-mirror.drift.src-jaffle-1",
        "catalog-mirror.drift.src-jaffle-2",
        "catalog-mirror.import.src-jaffle-1",
        "catalog-mirror.import.src-jaffle-2",
    ]
