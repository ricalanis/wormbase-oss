"""DriftDetectorReactivity, ClassificationRefreshReactivity, LineageHealthReactivity."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from wormbase_lake_maintainer.reactivities import (
    ClassificationRefreshReactivity,
    DriftDetectorReactivity,
    LineageHealthReactivity,
)


def _ctx():
    from wormbase_reactivities.protocol import ReactivityContext
    return ReactivityContext(
        ledger=AsyncMock(write=AsyncMock(return_value=None)),
        company_id=uuid4(),
        registry=MagicMock(),
        now=lambda: datetime.now(UTC),
    )


def _src_with_drift(drifted: bool):
    src = MagicMock()
    src.id = uuid4()
    src.family = "external"
    src.detect_drift = AsyncMock(return_value=MagicMock(
        drifted=drifted,
        reason="hash changed" if drifted else "stable",
        baseline_hash="0x" + "01" * 64,
        current_hash="0x" + "02" * 64,
    ))
    return src


@pytest.mark.asyncio
async def test_drift_reactivity_fires_when_drifted() -> None:
    react = DriftDetectorReactivity(source=_src_with_drift(True))
    entry = {"kind": "execute", "payload": {"tool": "emit_source_profiled"}}
    result = await react.fire(entry, _ctx())
    assert result.fired is True
    assert result.actions[0].action_kind == "source_drift_detected"


@pytest.mark.asyncio
async def test_drift_reactivity_no_op_when_not_drifted() -> None:
    react = DriftDetectorReactivity(source=_src_with_drift(False))
    entry = {"kind": "execute", "payload": {"tool": "emit_source_profiled"}}
    result = await react.fire(entry, _ctx())
    assert result.fired is False


@pytest.mark.asyncio
async def test_classification_reactivity_no_op_when_unchanged() -> None:
    src = MagicMock()
    src.id = uuid4()
    src.family = "external"
    src.refresh_classification = AsyncMock(return_value=MagicMock(
        updated=False, classification="internal",
        previous_classification="internal", reason="",
    ))
    react = ClassificationRefreshReactivity(source=src)
    entry = {"kind": "execute", "payload": {"tool": "emit_source_profiled"}}
    result = await react.fire(entry, _ctx())
    assert result.fired is False


@pytest.mark.asyncio
async def test_classification_reactivity_fires_when_classification_changed() -> None:
    src = MagicMock()
    src.id = uuid4()
    src.family = "external"
    src.refresh_classification = AsyncMock(return_value=MagicMock(
        updated=True, classification="pii",
        previous_classification="internal", reason="detected SSN pattern",
    ))
    react = ClassificationRefreshReactivity(source=src)
    entry = {"kind": "execute", "payload": {"tool": "emit_source_profiled"}}
    result = await react.fire(entry, _ctx())
    assert result.fired is True
    assert result.actions[0].action_kind == "source_classification_refreshed"


@pytest.mark.asyncio
async def test_lineage_reactivity_no_op_when_healthy() -> None:
    src = MagicMock()
    src.id = uuid4()
    src.family = "evidence"
    src.lineage_health = AsyncMock(return_value=MagicMock(
        healthy=True, broken_edges=[],
    ))
    react = LineageHealthReactivity(source=src)
    entry = {"kind": "execute", "payload": {"tool": "emit_source_profiled"}}
    result = await react.fire(entry, _ctx())
    assert result.fired is False


@pytest.mark.asyncio
async def test_lineage_reactivity_fires_when_broken_edges_present() -> None:
    src = MagicMock()
    src.id = uuid4()
    src.family = "evidence"
    src.lineage_health = AsyncMock(return_value=MagicMock(
        healthy=False,
        broken_edges=[MagicMock(
            upstream_kind="source", upstream_id="s1",
            downstream_kind="kpi", downstream_id="k1",
            healthy=False, reason="source retired",
        )],
    ))
    react = LineageHealthReactivity(source=src)
    entry = {"kind": "execute", "payload": {"tool": "emit_source_profiled"}}
    result = await react.fire(entry, _ctx())
    assert result.fired is True
    assert result.actions[0].action_kind == "source_lineage_break_detected"
