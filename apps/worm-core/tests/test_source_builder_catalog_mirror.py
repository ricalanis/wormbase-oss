"""SourceBuilder.on_source_connected dispatches catalog-mirror per upstream_mirror source.

Wave 3 Task 7 (2026-05-11): the dispatch now reads
``source.source_mode == "upstream_mirror"`` directly (the explicit
field on the ``MaintainableSource`` Protocol), replacing the Wave 1
cleanup 1a ``catalog_source is not None`` heuristic. This suite pins
the dispatch contract:

* upstream_mirror sources (``source_mode == "upstream_mirror"``)
  register BOTH the 4 lake-maintainer Reactivities AND the 2
  catalog-mirror Reactivities. The source also carries a
  ``catalog_source`` instance, which the catalog-mirror wire reads
  to construct the Reactivities.
* wormbase_owned sources (``source_mode == "wormbase_owned"``, the
  default) register only the 4 lake-maintainer Reactivities —
  catalog-mirror does NOT fire.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from wormbase_core.source_builder import SourceBuilder
from wormbase_lake_maintainer.registry import SourceRegistry


@pytest.mark.asyncio
async def test_upstream_mirror_source_registers_both_lake_and_catalog() -> None:
    """upstream_mirror source → 4 lake-maintainer + 2 catalog-mirror Reactivities."""
    company = uuid4()
    source_registry = SourceRegistry(company_id=company)
    reactivity_registry = MagicMock()
    reactivity_registry.register = MagicMock()
    builder = SourceBuilder(
        ledger=AsyncMock(),
        source_registry=source_registry,
        reactivity_registry=reactivity_registry,
    )

    # Upstream-mirror source: explicit source_mode triggers dispatch.
    # The catalog_source instance is still required — the catalog-mirror
    # wire reads it to construct the per-source Reactivities. source_mode
    # is the dispatch signal; catalog_source is the construction input.
    upstream_source = MagicMock()
    upstream_source.id = uuid4()
    upstream_source.family = "external"
    upstream_source.domain_id = "domain-finance"
    upstream_source.source_mode = "upstream_mirror"
    upstream_source.catalog_source = MagicMock()
    upstream_source.secrets = {}

    registered = await builder.on_source_connected(upstream_source)

    # Lake-maintainer registered the source.
    sources = await source_registry.list_sources()
    assert len(sources) == 1

    # 4 lake-maintainer + 2 catalog-mirror = 6 total registrations.
    assert reactivity_registry.register.call_count == 6
    # Returned list mirrors the registrations.
    assert len(registered) == 6


@pytest.mark.asyncio
async def test_wormbase_owned_source_skips_catalog_mirror() -> None:
    """wormbase_owned source (default source_mode) → 4 lake-maintainer only."""
    company = uuid4()
    source_registry = SourceRegistry(company_id=company)
    reactivity_registry = MagicMock()
    reactivity_registry.register = MagicMock()
    builder = SourceBuilder(
        ledger=AsyncMock(),
        source_registry=source_registry,
        reactivity_registry=reactivity_registry,
    )

    # wormbase_owned source: source_mode is the Protocol default.
    class _OwnedSource:
        id = uuid4()
        family = "external"
        source_mode = "wormbase_owned"

    registered = await builder.on_source_connected(_OwnedSource())

    sources = await source_registry.list_sources()
    assert len(sources) == 1

    # Only lake-maintainer's 4 Reactivities — catalog-mirror does NOT fire.
    assert reactivity_registry.register.call_count == 4
    assert len(registered) == 4


@pytest.mark.asyncio
async def test_missing_source_mode_defaults_to_wormbase_owned() -> None:
    """Source missing ``source_mode`` falls through as wormbase_owned (back-compat).

    The dispatch reads via ``getattr(source, "source_mode",
    "wormbase_owned")``, so sources predating the Protocol field
    continue to register only the 4 lake-maintainer Reactivities.
    """
    company = uuid4()
    source_registry = SourceRegistry(company_id=company)
    reactivity_registry = MagicMock()
    reactivity_registry.register = MagicMock()
    builder = SourceBuilder(
        ledger=AsyncMock(),
        source_registry=source_registry,
        reactivity_registry=reactivity_registry,
    )

    class _LegacySource:
        id = uuid4()
        family = "external"
        # No source_mode field at all — getattr default kicks in.

    registered = await builder.on_source_connected(_LegacySource())
    assert reactivity_registry.register.call_count == 4
    assert len(registered) == 4
