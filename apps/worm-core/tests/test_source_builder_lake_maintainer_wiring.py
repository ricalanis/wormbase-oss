"""SourceBuilder calls wire_maintenance_for_source after a successful connect."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from wormbase_core.source_builder import SourceBuilder
from wormbase_lake_maintainer.registry import SourceRegistry


@pytest.mark.asyncio
async def test_on_source_connected_calls_wire_maintenance() -> None:
    company = uuid4()
    source_registry = SourceRegistry(company_id=company)
    reactivity_registry = MagicMock()
    reactivity_registry.register = MagicMock()
    builder = SourceBuilder(
        ledger=AsyncMock(),
        source_registry=source_registry,
        reactivity_registry=reactivity_registry,
    )
    # wormbase_owned source: source_mode is the Protocol default, so
    # catalog-mirror dispatch is skipped and only the 4 lake-maintainer
    # Reactivities fire. (Wave 3 Task 7 — catalog-mirror routes
    # per-source via ``source.source_mode == "upstream_mirror"``,
    # replacing the Wave 1 cleanup 1a heuristic.)
    fake_source = MagicMock()
    fake_source.id = uuid4()
    fake_source.family = "external"
    fake_source.source_mode = "wormbase_owned"
    await builder.on_source_connected(fake_source)
    sources = await source_registry.list_sources()
    assert len(sources) == 1
    assert reactivity_registry.register.call_count == 4


@pytest.mark.asyncio
async def test_on_source_connected_no_op_without_registries() -> None:
    """Backward compat: SourceBuilder without lake-maintainer kwargs returns []."""
    builder = SourceBuilder(ledger=AsyncMock())
    fake_source = MagicMock()
    fake_source.id = uuid4()
    fake_source.family = "external"
    fake_source.source_mode = "wormbase_owned"
    result = await builder.on_source_connected(fake_source)
    assert result == []
