"""wire_maintenance_for_source: register the 4 Reactivities with W5a."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from wormbase_lake_maintainer.registry import (
    SourceRegistry,
    wire_maintenance_for_source,
)


def _src(family: str = "external"):
    src = MagicMock()
    src.id = uuid4()
    src.family = family
    return src


@pytest.mark.asyncio
async def test_wire_registers_4_reactivities() -> None:
    reactivity_registry = MagicMock()
    reactivity_registry.register = MagicMock()
    src = _src()
    source_registry = SourceRegistry(company_id=uuid4())
    reactivities = await wire_maintenance_for_source(
        source=src,
        source_registry=source_registry,
        reactivity_registry=reactivity_registry,
    )
    assert len(reactivities) == 4
    assert reactivity_registry.register.call_count == 4


@pytest.mark.asyncio
async def test_wire_adds_source_to_source_registry() -> None:
    reactivity_registry = MagicMock()
    src = _src()
    source_registry = SourceRegistry(company_id=uuid4())
    await wire_maintenance_for_source(
        source=src,
        source_registry=source_registry,
        reactivity_registry=reactivity_registry,
    )
    sources = await source_registry.list_sources()
    assert len(sources) == 1
    assert sources[0].id == src.id


@pytest.mark.asyncio
async def test_wire_returns_reactivity_ids() -> None:
    reactivity_registry = MagicMock()
    src = _src()
    source_registry = SourceRegistry(company_id=uuid4())
    reactivities = await wire_maintenance_for_source(
        source=src,
        source_registry=source_registry,
        reactivity_registry=reactivity_registry,
    )
    ids = {r.id for r in reactivities}
    assert any("staleness" in i for i in ids)
    assert any("drift" in i for i in ids)
    assert any("classification" in i for i in ids)
    assert any("lineage" in i for i in ids)
