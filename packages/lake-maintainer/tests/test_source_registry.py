"""SourceRegistry: per-tenant MaintainableSource set."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from wormbase_lake_maintainer.registry import SourceRegistry


def _src(family: str = "external"):
    src = MagicMock()
    src.id = uuid4()
    src.family = family
    return src


@pytest.mark.asyncio
async def test_register_then_list() -> None:
    reg = SourceRegistry(company_id=uuid4())
    src1 = _src("external")
    src2 = _src("conversation")
    await reg.register(src1)
    await reg.register(src2)
    sources = await reg.list_sources()
    assert {s.id for s in sources} == {src1.id, src2.id}


@pytest.mark.asyncio
async def test_register_is_idempotent_by_id() -> None:
    reg = SourceRegistry(company_id=uuid4())
    src = _src()
    await reg.register(src)
    await reg.register(src)
    sources = await reg.list_sources()
    assert len(sources) == 1


@pytest.mark.asyncio
async def test_filter_by_family() -> None:
    reg = SourceRegistry(company_id=uuid4())
    await reg.register(_src("external"))
    await reg.register(_src("external"))
    await reg.register(_src("evidence"))
    externals = await reg.list_sources(family="external")
    assert len(externals) == 2
    evidences = await reg.list_sources(family="evidence")
    assert len(evidences) == 1


@pytest.mark.asyncio
async def test_deregister_removes_source() -> None:
    reg = SourceRegistry(company_id=uuid4())
    src = _src()
    await reg.register(src)
    await reg.deregister(src.id)
    assert await reg.list_sources() == []
