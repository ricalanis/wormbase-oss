"""make_maintenance_reactivities — produces 4 Reactivities per Source."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from wormbase_lake_maintainer.factory import make_maintenance_reactivities
from wormbase_lake_maintainer.reactivities import (
    ClassificationRefreshReactivity,
    DriftDetectorReactivity,
    LineageHealthReactivity,
    StalenessSignalReactivity,
)


def _src(family: str = "external"):
    src = MagicMock()
    src.id = uuid4()
    src.family = family
    return src


@pytest.mark.asyncio
async def test_factory_returns_four_reactivities() -> None:
    reactivities = make_maintenance_reactivities(source=_src())
    assert len(reactivities) == 4
    types = {type(r) for r in reactivities}
    assert types == {
        StalenessSignalReactivity,
        DriftDetectorReactivity,
        ClassificationRefreshReactivity,
        LineageHealthReactivity,
    }


@pytest.mark.asyncio
async def test_factory_each_reactivity_carries_unique_id() -> None:
    src = _src()
    ids = {r.id for r in make_maintenance_reactivities(source=src)}
    assert len(ids) == 4


@pytest.mark.asyncio
async def test_factory_works_for_each_family() -> None:
    for family in ["external", "filedrop", "conversation", "evidence"]:
        rs = make_maintenance_reactivities(source=_src(family=family))
        assert len(rs) == 4
